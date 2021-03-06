from typing import Union

from db_query import DBQuery
import numpy as np
from utils import convert_list_to_dict
from dialogue_config import all_intents, all_slots, usersim_default_key, DialogAction
import copy


class StateTracker:
    def __init__(self, database, max_round_num):

        self.db_helper = DBQuery(database)
        self.match_key = usersim_default_key
        self.intents_dict = convert_list_to_dict(all_intents)
        self.num_intents = len(all_intents)
        self.slots_dict = convert_list_to_dict(all_slots)
        self.num_slots = len(all_slots)
        self.max_round_num = max_round_num
        self.none_state = np.zeros(self.get_state_size())
        self.reset()

    def get_state_size(self):
        return 2 * self.num_intents + 7 * self.num_slots + 3 + self.max_round_num

    def reset(self):
        self.current_informs = {}
        # A list of the dialogues (dicts) by the agent and user so far in the conversation
        self.history = []
        self.round_num = 0

    def print_history(self):
        """Helper function if you want to see the current history action by action."""

        for action in self.history:
            print(action)

    def get_state(self, done=False) -> np.ndarray:

        if done:
            return self.none_state

        user_action: DialogAction = self.history[-1]
        db_results_dict = self.db_helper.get_db_results_for_slots(self.current_informs)
        last_agent_action: Union[DialogAction, None] = self.history[-2] if len(
            self.history
        ) > 1 else None

        # Create one-hot of intents to represent the current user action
        user_act_rep = np.zeros((self.num_intents,))
        user_act_rep[self.intents_dict[user_action.intent]] = 1.0

        # Create bag of inform slots representation to represent the current user action
        user_inform_slots_rep = np.zeros((self.num_slots,))
        for key in user_action.inform_slots.keys():
            user_inform_slots_rep[self.slots_dict[key]] = 1.0

        # Create bag of request slots representation to represent the current user action
        user_request_slots_rep = np.zeros((self.num_slots,))
        for key in user_action.request_slots.keys():
            user_request_slots_rep[self.slots_dict[key]] = 1.0

        # Create bag of filled_in slots based on the current_slots
        current_slots_rep = np.zeros((self.num_slots,))
        for key in self.current_informs:
            current_slots_rep[self.slots_dict[key]] = 1.0

        # Encode last agent intent
        agent_act_rep = np.zeros((self.num_intents,))
        if last_agent_action:
            agent_act_rep[self.intents_dict[last_agent_action.intent]] = 1.0

        # Encode last agent inform slots
        agent_inform_slots_rep = np.zeros((self.num_slots,))
        if last_agent_action and last_agent_action.inform_slots is not None:
            for key in last_agent_action.inform_slots.keys():
                agent_inform_slots_rep[self.slots_dict[key]] = 1.0

        # Encode last agent request slots
        agent_request_slots_rep = np.zeros((self.num_slots,))
        if last_agent_action and last_agent_action.request_slots is not None:
            for key in last_agent_action.request_slots.keys():
                agent_request_slots_rep[self.slots_dict[key]] = 1.0

        # Value representation of the round num
        turn_rep = np.zeros((1,)) + self.round_num / 5.0

        # One-hot representation of the round num
        turn_onehot_rep = np.zeros((self.max_round_num,))
        turn_onehot_rep[self.round_num - 1] = 1.0

        # Representation of DB query results (scaled counts)
        kb_count_rep = (
            np.zeros((self.num_slots + 1,))
            + db_results_dict["matching_all_constraints"] / 100.0
        )
        for key in db_results_dict.keys():
            if key in self.slots_dict:
                kb_count_rep[self.slots_dict[key]] = db_results_dict[key] / 100.0

        # Representation of DB query results (binary)
        kb_binary_rep = np.zeros((self.num_slots + 1,)) + np.sum(
            db_results_dict["matching_all_constraints"] > 0.0
        )
        for key in db_results_dict.keys():
            if key in self.slots_dict:
                kb_binary_rep[self.slots_dict[key]] = np.sum(db_results_dict[key] > 0.0)

        state_representation = np.hstack(
            [
                user_act_rep,
                user_inform_slots_rep,
                user_request_slots_rep,
                agent_act_rep,
                agent_inform_slots_rep,
                agent_request_slots_rep,
                current_slots_rep,
                turn_rep,
                turn_onehot_rep,
                kb_binary_rep,
                kb_count_rep,
            ]
        ).flatten()

        return state_representation

    def update_state_agent(self, agent_action: DialogAction):

        if agent_action.intent == "inform":
            self.handle_inform_with_db_query(agent_action)
        elif agent_action.intent == "match_found":
            self.handle_match_found(agent_action)

        agent_action.turn = self.round_num
        self.history.append(agent_action)

    def handle_match_found(self, agent_action: DialogAction):
        # If intent is match_found then fill the action informs with the matches informs (if there is a match)
        assert agent_action.inform_slots is None
        db_results = self.db_helper.get_db_results(self.current_informs)
        if db_results:
            item_idx, item = list(db_results.items())[0]
            agent_action.inform_slots = copy.deepcopy(item)
            agent_action.inform_slots[self.match_key] = str(item_idx)
        else:
            agent_action.inform_slots = {self.match_key: "no match available"}

        value = agent_action.inform_slots[self.match_key]
        self.current_informs[self.match_key] = value

    def handle_inform_with_db_query(self, agent_action: DialogAction):
        assert agent_action.inform_slots
        slot_name = list(agent_action.inform_slots.keys())[0]
        value = self.db_helper.get_inform_value(slot_name, self.current_informs)
        agent_action.inform_slots = {slot_name: value}
        key, value = list(agent_action.inform_slots.items())[0]  # Only one
        assert key != "match_found"
        assert value != "PLACEHOLDER", "KEY: {}".format(key)
        self.current_informs[key] = value

    def update_state_user(self, user_action: DialogAction):

        for key, value in user_action.inform_slots.items():
            self.current_informs[key] = value

        user_action.turn = self.round_num
        self.history.append(user_action)
        self.round_num += 1
