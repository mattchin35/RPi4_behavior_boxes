
# put all of your mouse and session info in here

from datetime import datetime
import os
import pysistence, collections
import socket

# defining immutable mouse dict (once defined for a mouse, NEVER EDIT IT)
mouse_info = pysistence.make_dict({'mouse_name': 'test',
                 'fake_field': 'fake_info',
                 })

# Information for this session (the user should edit this each session)
session_info                              	= collections.OrderedDict()
session_info['mouse_info']					= mouse_info
session_info['mouse_name']                 	= mouse_info['mouse_name']

session_info['basedir']					  	= '/home/pi/buffer'
session_info['external_storage']            = '/mnt/hd'
session_info['flipper_filename']            = '/home/pi/buffer/flipper_timestamp'
# for actual data save to this dir:
# session_info['basedir']					  	= '/home/pi/video'
session_info['weight']                	    = 0.0
session_info['manual_date']					= '202x-xx-xx'
session_info['box_name']             		= socket.gethostname()
session_info['block_number']                = 1 # 1 (left large) or 2 (right large) which block starts


session_info['config']						= 'headfixed2FC'

# behavior parameters
session_info['timeout_length']              = 5  # in seconds
session_info['reward_size']					= 10  # in microliters
session_info["lick_threshold"]              = 1
# visual stimulus
session_info["visual_stimulus"]             = False

session_info['config']	                    = 'headfixed2FC'
session_info['treadmill_setup']             = {}
session_info['treadmill']                    = True
session_info['phase']                   	= 1

if session_info['treadmill']:
    session_info['treadmill_setup']['distance_initiation'] = 10  # cm
    session_info['treadmill_setup']['distance'] = 10  # cm
else:
    session_info['treadmill_setup'] = None

session_info['error_repeat'] = True
if session_info['error_repeat']:
    session_info['error_max'] = 3

# condition setup
session_info['cue'] = ['LED_L', 'LED_R', 'all']
session_info['state'] = ['block1', 'block2']  # treadmill distance
session_info['choice'] = ['right', 'left']  # lick port
session_info['reward'] = ['small', 'large']  # reward size
session_info['reward_size'] = {'small': 5, 'large': 10}

if session_info['phase'] == 1:
    session_info['reward_size'] = {'small': 10, 'large': 10}

# define timeout during each condition
session_info['initiation_timeout'] = 120  # s
session_info['cue_timeout'] = 120
session_info['reward_timeout'] = 60
session_info["punishment_timeout"] = 1

# define block_duration and initial block to start the session
session_info['block_duration'] = 30  # each block has this amount of repetition
session_info['block_variety'] = 2
if session_info['block_variety'] > 1:
    session_info['initial_block'] = 1

session_info['consecutive_control'] = False
if session_info['consecutive_control']:
    session_info['consecutive_max'] = 3
