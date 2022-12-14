import json
import os
import random
import sys
import time
from collections import deque
from datetime import datetime, timedelta

import tensorflow.keras as keras
import numpy as np
import skimage.color
import skimage.exposure
import skimage.transform
from tensorflow.keras import layers, models

from game import wrapped_flappy_bird as game
from utils import logging


ACTIONS = 2  # number of valid actions
GAMMA = 0.99  # decay rate of past observations
# TOTAL_OBSERVATION = 3_200 # timesteps to observe before training
TOTAL_EXPLORE = 30_000  # 3000000. # frames over which to anneal epsilon
INITIAL_EPSILON = 0.1  # starting value of epsilon
FINAL_EPSILON = 0.0001  # final value of epsilon
REPLAY_MEMORY = 20_000  # 30000 # number of previous transitions to remember
BATCH = 32  # size of minibatch
FRAME_PER_ACTION = 1
LEARNING_RATE = 1e-4


def init_network(observe, epsilon, mode, filename=None):
    print("Now we init the network")

    img_rows, img_cols = 80, 80
    # Convert image into Black and white
    img_channels = 4  # We stack 4 frames

    network = models.Sequential()
    network.add(
        layers.Conv2D(
            32, (8, 8),
            activation='relu', strides=(4, 4),
            padding='same', input_shape=(img_rows, img_cols, img_channels)))  # 80*80*4
    network.add(
        layers.Conv2D(
            64, (4, 4),
            activation='relu', strides=(2, 2),
            padding='same'))
    network.add(
        layers.Conv2D(
            64, (3, 3),
            activation='relu', strides=(1, 1),
            padding='same'))
    network.add(layers.Flatten())
    network.add(layers.Dense(512, activation='relu'))
    network.add(layers.Dense(2))

    network.compile(loss='mse', optimizer=keras.optimizers.Adam(
        lr=LEARNING_RATE))
    print("We finished init the network")

    if mode == 'test':
        observe = 999999999  # We keep observe, never train
        epsilon = FINAL_EPSILON
        print("Now we load the model")
        try:
            network = keras.models.load_model(filename)
        except (OSError, IOError) as e:
            print(e)
            exit()
        print("The model has been loaded successfully")
        print("***** We are in testing mode *****")
    else:
        assert mode == 'train'
        print("***** We are in training mode *****")

    return network


def get_init_stack(game_state):
    # get the first state by doing nothing and preprocess the image to 80x80x4
    do_nothing = np.zeros(ACTIONS)
    do_nothing[0] = 1
    x_t_colored, _, _ = game_state.frame_step(do_nothing)

    x_t = skimage.color.rgb2gray(x_t_colored)
    x_t = skimage.transform.resize(x_t, (80, 80))
    x_t = skimage.exposure.rescale_intensity(x_t, out_range=(0, 255))

    x_t = x_t / 255.0

    s_t0 = np.stack((x_t, x_t, x_t, x_t), axis=2)
    # print (s_t.shape)

    # In Keras, need to reshape
    s_t0 = s_t0.reshape(
        1, s_t0.shape[0],
        s_t0.shape[1],
        s_t0.shape[2])  # 1*80*80*4
    return s_t0


def get_next_stack(game_state, a_t, s_t0):
    # run the selected action and observed next state and reward
    x_t1_colored, r_t, terminal = game_state.frame_step(a_t)

    x_t1 = skimage.color.rgb2gray(x_t1_colored)
    x_t1 = skimage.transform.resize(x_t1, (80, 80))
    x_t1 = skimage.exposure.rescale_intensity(x_t1, out_range=(0, 255))

    x_t1 = x_t1 / 255.0

    x_t1 = x_t1.reshape(1, x_t1.shape[0], x_t1.shape[1], 1)  # 1x80x80x1
    s_t1 = np.append(x_t1, s_t0[:, :, :, :3], axis=3)

    return s_t1, r_t, terminal


def train_network(queue, network):
    # sample a minibatch to train on
    minibatch = random.sample(queue, BATCH)

    # Now we do the experience replay
    state_t, action_t, reward_t, state_t1, terminal = zip(*minibatch)
    state_t = np.concatenate(state_t)
    state_t1 = np.concatenate(state_t1)
    targets = network.predict(state_t)
    Q_sa = network.predict(state_t1)
    targets[range(BATCH), action_t] = reward_t + GAMMA*np.max(Q_sa,
                                                              axis=1)*np.invert(terminal)

    loss = network.train_on_batch(state_t, targets)
    return loss, Q_sa


def chose_action(network, s_t, a_t, t, epsilon):
    # choose an action epsilon greedy
    if t % FRAME_PER_ACTION == 0:
        if random.random() <= epsilon:
            print("----------Random Action----------")
            action_index = random.randrange(ACTIONS)
        else:
            # input a stack of 4 images, get the prediction
            q = network.predict(s_t)
            max_Q = np.argmax(q)
            action_index = max_Q
    else:
        assert False
    return action_index


def q_learning(mode, filename=None):

    if mode == 'test':
        TOTAL_OBSERVATION = 1_000
    else:
        TOTAL_OBSERVATION = 3_200

    observe = TOTAL_OBSERVATION
    epsilon = INITIAL_EPSILON

    # init network
    network = init_network(observe, epsilon, mode, filename)

    # open up a game state to communicate with emulator
    game_state = game.GameState()

    # store the previous observations in replay memory
    queue = deque(maxlen=REPLAY_MEMORY)

    s_t0 = get_init_stack(game_state)

    t = 0
    time0 = time.time()
    total_loss = 0
    while (True):
        action_index, r_t = 0, 0
        a_t = np.zeros([ACTIONS])
        action_index = chose_action(network, s_t0, a_t, t, epsilon)
        a_t[action_index] = 1

        # We reduced the epsilon gradually
        if epsilon > FINAL_EPSILON and t > observe:
            epsilon -= (INITIAL_EPSILON - FINAL_EPSILON) / TOTAL_EXPLORE

        s_t1, r_t, terminal = get_next_stack(game_state, a_t, s_t0)

        queue.append((s_t0, action_index, r_t, s_t1, terminal))

        if t > observe:
            # only train if done observing
            loss, q_sa = train_network(queue, network)
        else:
            loss, q_sa = 0, 0

        total_loss += loss
        s_t0, t = s_t1, t + 1

        logging(mode, t, time0, network, observe, epsilon,
                action_index, r_t, q_sa, loss, total_loss, TOTAL_EXPLORE)

    print("Episode finished!")
    print("************************")


if __name__ == '__main__':
    # make TOTAL_OBSERVATION much smaller, and call train directly
    TOTAL_OBSERVATION = 32
    q_learning('train')
