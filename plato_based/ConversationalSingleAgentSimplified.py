import DataBase
import Goal
import Ontology
from dialog_action_classes import DialogueAct

from AgendaBasedUS import AgendaBasedUS
from ErrorModel import ErrorModel
import DialogueManager_simplified as DialogueManager
from slot_filling_reward_function import SlotFillingReward
from DialogueEpisodeRecorder import DialogueEpisodeRecorder, TurnState

from copy import deepcopy

import os
import random


def build_domain_settings(dialogue_config):

    assert os.path.isfile(dialogue_config["ontology_path"])

    ontology = Ontology.Ontology(dialogue_config["ontology_path"])
    assert os.path.isfile(dialogue_config["db_path"])

    cache_sql_results = False
    database = DataBase.SQLDataBase(
        dialogue_config["db_path"], cache_sql_results
    )
    return ontology, database


class ConversationalSingleAgent:
    def __init__(self, configuration):

        super().__init__()

        # There is only one agent in this setting
        self.agent_id = 0

        # Dialogue statistics
        self.dialogue_episode = 0
        self.dialogue_turn = 0
        self.num_successful_dialogues = 0
        self.num_task_success = 0
        self.cumulative_rewards = 0
        self.total_dialogue_turns = 0

        self.minibatch_length = 50
        self.train_interval = 10
        self.num_batches_per_epoch = 10

        self.SAVE_LOG = True

        # The dialogue will terminate after MAX_TURNS (this agent will issue
        # a bye() dialogue act.
        self.MAX_TURNS = 15

        self.dialogue_turn = -1
        self.dialogue_manager = None
        self.user_model = None

        self.agent_goal = None
        self.goal_generator = None

        self.prev_turnstate = TurnState()
        self.curr_state = None

        self.recorder = DialogueEpisodeRecorder()

        # TODO: Handle this properly - get reward function type from config
        self.reward_func = SlotFillingReward()

        self.ontology, self.database = build_domain_settings(configuration["DIALOGUE"])
        self.user_simulator = AgendaBasedUS(
            goal_generator=Goal.GoalGenerator(self.ontology, self.database),
            error_model=ErrorModel(
                self.ontology,
                slot_confuse_prob=0.0,
                op_confuse_prob=0.0,
                value_confuse_prob=0.0,
            ),
        )

        self.dialogue_manager = DialogueManager.DialogueManager(
            configuration,
            self.ontology,
            self.database,
            self.agent_id,
            "system",
            configuration["AGENT_0"]["DM"]["policy"],
        )

    def initialize(self):

        self.dialogue_episode = 0
        self.dialogue_turn = 0
        self.num_successful_dialogues = 0
        self.num_task_success = 0
        self.cumulative_rewards = 0

        self.dialogue_manager.initialize({})
        self.prev_turnstate = TurnState()
        self.curr_state = None

    def start_dialogue(self, args=None):

        self.dialogue_turn = 0
        self.user_simulator.initialize()

        self.dialogue_manager.restart({})
        sys_response = [DialogueAct("welcomemsg", [])]

        rew, success = self.process_system_action(sys_response)

        curr_state = self.dialogue_manager.get_state()
        turnstate = TurnState(curr_state, sys_response, rew, success)
        self.recorder.record(deepcopy(curr_state), turnstate)

        self.dialogue_turn += 1
        self.prev_turnstate = TurnState()
        self.curr_state = None

        self.continue_dialogue()

    def process_system_action(self, sys_response):
        self.user_simulator.receive_input(sys_response)
        rew, success = self.reward_func.calculate(
            state=self.dialogue_manager.get_state(), goal=self.user_simulator.goal
        )
        return rew, success

    def continue_dialogue(self):

        usr_input = self.user_simulator.respond()

        self.dialogue_manager.receive_input(usr_input)

        # Keep track of prev_state, for the DialogueEpisodeRecorder
        # Store here because this is the state that the dialogue manager
        # will use to make a decision.
        self.curr_state = deepcopy(self.dialogue_manager.get_state())

        if self.dialogue_turn < self.MAX_TURNS:
            sys_response = self.dialogue_manager.generate_output()

        else:
            sys_response = [DialogueAct("bye", [])]

        rew, success = self.process_system_action(sys_response)

        if self.prev_turnstate.state is not None:
            self.recorder.record(self.curr_state, self.prev_turnstate)

        self.dialogue_turn += 1

        self.prev_turnstate = TurnState(
            deepcopy(self.curr_state), deepcopy(sys_response), rew, success
        )

    def end_dialogue(self):

        self.recorder.record(self.curr_state, self.prev_turnstate)

        if (
            self.dialogue_manager.is_training()
            and self.dialogue_episode % self.train_interval == 0
            and len(self.recorder.dialogues) >= self.minibatch_length
        ):
            self.train_for_n_batches(self.num_batches_per_epoch)

        self.dialogue_episode += 1
        self.cumulative_rewards += self.recorder.dialogues[-1][-1].cumulative_reward

        if self.dialogue_turn > 0:
            self.total_dialogue_turns += self.dialogue_turn

        if self.dialogue_episode % 10000 == 0:
            self.dialogue_manager.save()

        # Count successful dialogues
        dialogue_success = self.recorder.dialogues[-1][-1].success
        if dialogue_success:
            self.num_successful_dialogues += int(dialogue_success)

    def train_for_n_batches(self,num_batches):
        for _ in range(num_batches):
            minibatch = random.sample(
                self.recorder.dialogues, self.minibatch_length
            )
            self.dialogue_manager.train(minibatch)

    def terminated(self):
        return self.dialogue_manager.at_terminal_state()
