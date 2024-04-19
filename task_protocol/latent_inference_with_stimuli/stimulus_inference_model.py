from task_protocol.latent_inference_forage.latent_inference_forage_model import LatentInferenceForageModel

from icecream import ic
import logging
import time

import numpy as np
import random

import logging.config
from collections import deque
from typing import List, Tuple, Union

import logging.config
import threading

# SEED = 0
# random.seed(SEED)
RIGHT_IX = 0
LEFT_IX = 1


class StimulusInferenceModel(LatentInferenceForageModel):
    """
    Subclass of the LatentInferenceForageModel class, which is a subclass of the Model class from the essential package.
    The only thing this needs to add on top of the LatentInferenceForageModel is the ability to (probabilistically)
    turn on and off stimuli.
    """

    def __init__(self, session_info: dict):
        super().__init__(session_info)
        self.stimulus_thread = None
        self.L_stimulus_active = False
        self.R_stimulus_active = False
        self.t_stimulus_start = None
        self.stimulus_duration = 0.5  # session_info['stimulus_duration']
        self.p_stimulus = 0.25  # session_info['p_stimulus']

    def L_stimulus_on(self) -> None:
        self.L_stimulus_active = True
        self.presenter_commands.append('turn_L_stimulus_on')
        t = threading.Timer(interval=self.stimulus_duration, function=self.L_stimulus_off)
        self.t_stimulus_start = time.perf_counter()
        t.start()
        self.stimulus_thread = t

    def L_stimulus_off(self) -> None:
        self.L_stimulus_active = False
        self.presenter_commands.append('turn_L_stimulus_off')

    def R_stimulus_on(self) -> None:
        self.R_stimulus_active = True
        self.presenter_commands.append('turn_R_stimulus_on')
        t = threading.Timer(interval=self.stimulus_duration, function=self.R_stimulus_off)
        self.t_stimulus_start = time.perf_counter()
        t.start()
        self.stimulus_thread = t

    def stimuli_off(self) -> None:
        self.L_stimulus_active = False
        self.R_stimulus_active = False
        self.presenter_commands.append('turn_stimuli_off')

    def reset_stimuli(self) -> None:
        self.L_stimulus_active = False
        self.R_stimulus_active = False
        self.presenter_commands.append('reset_stimuli')

    def R_stimulus_off(self) -> None:
        self.R_stimulus_active = False
        self.presenter_commands.append('turn_R_stimulus_off')

    def enter_left_patch(self) -> None:
        logging.info(";" + str(time.time()) + ";[transition];enter_left_patch;" + str(""))
        if random.random() < self.p_stimulus:
            self.L_stimulus_on()
            logging.info(";" + str(time.time()) + ";[action];left_stimulus_on;" + str(""))

    def enter_right_patch(self) -> None:
        logging.info(";" + str(time.time()) + ";[transition];enter_right_patch;" + str(""))
        if random.random() < self.p_stimulus:
            self.R_stimulus_on()
            logging.info(";" + str(time.time()) + ";[action];right_stimulus_on;" + str(""))

    def activate_dark_period(self):
        # make sure this overrides ITI, so you don't get an LED turned on after darkmode starts
        self.ITI_active = False
        if self.ITI_thread:
            self.ITI_thread.cancel()

        # self.turn_LED_off()
        self.stimuli_off()
        self.reset_counters()
        self.switch_to_dark_period()

        t = threading.Timer(random.choice(self.session_info['dark_period_times']), self.end_dark_period)
        t.start()
        self.dark_period_thread = t