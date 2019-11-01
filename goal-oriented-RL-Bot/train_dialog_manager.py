import json
import pickle
from typing import Dict

import torch

import gym
from torch.optim.rmsprop import RMSprop
import numpy as np
from tqdm import tqdm
import torch.nn.functional as F


from dialog_agent_env import (
    UserGoal,
    DialogEnv,
    DialogManagerAgent,
    experience_generator,
    gather_experience,
    load_data)


def calc_estimated_return(
    agent: DialogManagerAgent, experience: Dict[str, np.ndarray], discount=0.99
):
    next_q_values = agent.calc_q_values(experience["next_obs"])
    max_next_value, _ = next_q_values.max(dim=1)
    mask = torch.tensor((1 - experience["next_done"]), dtype=torch.float)
    next_reward = torch.tensor(experience["next_reward"], dtype=torch.float)
    estimated_return = next_reward + discount * max_next_value * mask
    return estimated_return


def calc_loss(agent, estimated_return, observation, action):
    q_values = agent.calc_q_values(observation)
    actions_tensor = torch.tensor(action).unsqueeze(1)
    q_selected = q_values.gather(1, actions_tensor).squeeze(1)
    loss_value = F.mse_loss(q_selected, estimated_return)
    return loss_value


def train_agent(agent: DialogManagerAgent, dialog_env: DialogEnv, train_steps=3_000, batch_size=32):
    optimizer = RMSprop(agent.parameters())
    experience_iterator = iter(experience_generator(agent, dialog_env))

    for it in tqdm(range(train_steps)):
        with torch.no_grad():
            agent.eval()
            exp = gather_experience(experience_iterator, batch_size=batch_size)
            estimated_return = calc_estimated_return(agent, exp)

        agent.train()
        loss_value = calc_loss(agent, estimated_return, exp["obs"], exp["action"])
        optimizer.zero_grad()
        loss_value.backward()
        optimizer.step()




if __name__ == "__main__":

    def get_params(params_json_file="constants.json"):
        with open(params_json_file) as f:
            constants = json.load(f)
        return constants

    params = get_params()
    file_path_dict = params["db_file_paths"]
    DATABASE_FILE_PATH = file_path_dict["database"]
    DICT_FILE_PATH = file_path_dict["dict"]
    USER_GOALS_FILE_PATH = file_path_dict["user_goals"]

    train_params = params["run"]

    slot2values, database, user_goals = load_data(
        DATABASE_FILE_PATH, DICT_FILE_PATH, USER_GOALS_FILE_PATH
    )

    dialog_env = DialogEnv(
        user_goals, params["emc"], params["run"]["max_round_num"], database, slot2values
    )

    agent = DialogManagerAgent(dialog_env.observation_space, dialog_env.action_space)
    # experience_iterator = iter(experience_generator(agent, dialog_env))
    # batch = gather_experience(experience_iterator)
    train_agent(agent,dialog_env,100)
