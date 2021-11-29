
import struct
from bitarray import bitarray
import logging
from ilock import ILock
import sys
import numpy as np 
import time
import rtmidi
from rtmidi.midiutil import *
import mido
import math
import hjson as json
import socket
import os
import traceback
import pickle

import logging

logger = logging.getLogger('DT01')

MIDINOTES      = 128
CONTROLCOUNT   = 128
OPERATORCOUNT  = 8

controlNum2Name = [""]*CONTROLCOUNT

# common midi controls https://professionalcomposers.com/midi-cc-list/

# begin voice parameters
controlNum2Name[0 ] = "ctrl_vibrato_env"  # modwheel. tie it to vibrato (Pitch LFO)
controlNum2Name[1 ] = "ctrl_tremolo_env"  # breath control
controlNum2Name[4 ] = "ctrl_fbgain"         
controlNum2Name[5 ] = "ctrl_fbsrc"          

controlNum2Name[7 ] = "ctrl_voicegain"       # common midi control
controlNum2Name[10] = "ctrl_pan"             # common midi control
controlNum2Name[11] = "ctrl_expression"      # common midi control


OPBASE = [0]*8
# begin operator parameters
controlNum2Name[13] = "ctrl_opno"            
OPBASE[0]  = 14
controlNum2Name[14] = "ctrl_env"            
controlNum2Name[15] = "ctrl_env_rate"      
controlNum2Name[16] = "ctrl_envexp"         
controlNum2Name[17] = "ctrl_increment"      
controlNum2Name[18] = "ctrl_increment_rate"
controlNum2Name[19] = "ctrl_incexp"         
controlNum2Name[20] = "ctrl_fmsrc"         
controlNum2Name[21] = "ctrl_amsrc"         
controlNum2Name[22] = "ctrl_static"         
controlNum2Name[23] = "ctrl_sounding"         
   

# common midi controls
controlNum2Name[64] = "ctrl_sustain"         # common midi control
controlNum2Name[65] = "ctrl_ratemento"      # common midi control
controlNum2Name[71] = "ctrl_filter_resonance"# common midi control
controlNum2Name[74] = "ctrl_filter_cutoff"   # common midi control


# begin global params
controlNum2Name[110] = "ctrl_env_clkdiv"     
controlNum2Name[111] = "ctrl_flushspi"       
controlNum2Name[112] = "ctrl_passthrough"    
controlNum2Name[113] = "ctrl_shift"          

controlName2Num = {}
for i, name in enumerate(controlNum2Name):
	controlName2Num[name] = i
	if name:
		exec(name + " = " + str(i))

cmdName2number = {}
cmdName2number["cmd_readirqueue"    ] = 64
cmdName2number["cmd_readaudio"      ] = 65
cmdName2number["cmd_readid"         ] = 66
cmdName2number["cmd_static"         ] = 67
cmdName2number["cmd_sounding"       ] = 69
cmdName2number["cmd_fm_algo"        ] = 70
cmdName2number["cmd_am_algo"        ] = 71
cmdName2number["cmd_fbgain"         ] = 73
cmdName2number["cmd_fbsrc"          ] = 74
cmdName2number["cmd_channelgain"    ] = 75
cmdName2number["cmd_env"            ] = 76 
cmdName2number["cmd_env_rate"      ] = 77 
cmdName2number["cmd_envexp"         ] = 78 
cmdName2number["cmd_increment"      ] = 79 
cmdName2number["cmd_increment_rate"] = 80 
cmdName2number["cmd_incexp"         ] = 81
cmdName2number["cmd_flushspi"       ] = 120
cmdName2number["cmd_passthrough"    ] = 121
cmdName2number["cmd_shift"          ] = 122
cmdName2number["cmd_env_clkdiv"     ] = 123

cmdNum2Name = ["0"]*128
for name, number in cmdName2number.items():
	cmdNum2Name[number] = name
		
for name, number in cmdName2number.items():
	if name:
		#print(name + " = " + str(number))
		exec(name + " = " + str(number))


import inspect

def DT01_fromFile(filename):
	with open(filename, 'rb') as f:
		return pickle.load(f)

class DT01():

	def toFile(self, filename):
		with open(filename, 'wb+') as f:
			pickle.dump(self, f)
	
	def __init__(self, polyphony = 512):
		self.voices = 0
		self.polyphony = polyphony
		self.voicesPerPatch = min(self.polyphony, 64)
		self.patchesPerDT01 = int(round(self.polyphony / self.voicesPerPatch))
		self.voices = []
		self.voiceSets = []
		self.loanTime = [0]*self.patchesPerDT01
		
		index = 0
		for i in range(self.patchesPerDT01):
			newSet = []
			for j in range(self.voicesPerPatch):
				newVoice = Voice(index)
				self.voices += [newVoice]
				newSet      += [newVoice]
				index += 1
			self.voiceSets += [newSet]

	def getVoices(self):
		# return the longest since activation
		oldestSetIndex = np.argsort(self.loanTime)[0]
		return self.voiceSets[oldestSetIndex]
	
	
	def getInitCommands(self):
		lowestVoiceIndex = min([v.index for v in self.voices])
		
		commands = []
		commands += [formatCommand(cmd_static       , lowestVoiceIndex, 0, [0b11000000]*len(self.voices))]
		commands += [formatCommand(cmd_sounding     , lowestVoiceIndex, 0, [0b00000001]*len(self.voices))]
		commands += [formatCommand(cmd_fm_algo      , lowestVoiceIndex, 0, [0o77777777]*len(self.voices))]
		commands += [formatCommand(cmd_am_algo      , lowestVoiceIndex, 0, [0o00000000]*len(self.voices))]
		commands += [formatCommand(cmd_fbgain       , lowestVoiceIndex, 0, [0         ]*len(self.voices))]
		commands += [formatCommand(cmd_fbsrc        , lowestVoiceIndex, 0, [0         ]*len(self.voices))]
			
		for channel in range(2):
			commands += [formatCommand(cmd_channelgain, lowestVoiceIndex, 0, [2**16]*len(self.voices))]
			
		#paramNum, mm_opno,  voiceno,  payload
		for opno in range(OPERATORCOUNT):
			commands += [formatCommand(cmd_env            , lowestVoiceIndex, opno, [0   ]*len(self.voices))]
			commands += [formatCommand(cmd_env_rate       , lowestVoiceIndex, opno, [0   ]*len(self.voices))]
			commands += [formatCommand(cmd_envexp         , lowestVoiceIndex, opno, [0x01]*len(self.voices))]

		commands += [formatCommand(cmd_increment      , lowestVoiceIndex, 6, [2**12]*len(self.voices))] # * self.paramNum2Real[increment]
		commands += [formatCommand(cmd_increment      , lowestVoiceIndex, 7, [2**12]*len(self.voices))] # * self.paramNum2Real[increment]

		commands += [formatCommand(cmd_increment_rate , lowestVoiceIndex, 0, [0   ]*len(self.voices))]
		commands += [formatCommand(cmd_incexp         , lowestVoiceIndex, 0, [0x01]*len(self.voices))]

		commands += [formatCommand(cmd_flushspi     , 0, 0, 0)    ]
		commands += [formatCommand(cmd_passthrough  , 0, 0, 0)    ]
		commands += [formatCommand(cmd_shift        , 0, 0, 0)    ]
		commands += [formatCommand(cmd_env_clkdiv   , 0, 0, 5)]
		return commands
		
	def formatCommand(self, param, value):
		return formatCommand(param, 0, 0, value)
	
		
class Voice():
		
	def __init__(self, index):
		self.index = index
		self.spawntime = 0
		self.index = index
		self.note = None
		self.sounding = False    
		self.defaultIncrement = 0
		self.indexInCluster = 0
		self.operators = []
		for opindex in range(OPERATORCOUNT):
			self.operators += [Operator(self, opindex)]
		
		self.channels = []
		self.channels += [Channel(self, 0)]
		self.channels += [Channel(self, 1)]
		
		self.allChildren = self.channels + self.operators 
			
	def formatCommand(self, param, value):
		return formatCommand(param, self.index, 0, value)


class Channel():
	def __init__(self, voice, index):
		self.index = index
		self.voice = voice
		self.selected = False
		
	def formatCommand(self, param, value):
		return formatCommand(param, self.voice.index, self.index, value)
		

# OPERATOR DESCRIPTIONS
class Operator():
	def __init__(self, voice, index):
		self.index = index
		self.voice = voice
		self.base  = OPBASE[self.index]
		self.sounding = 0
		self.fmsrc    = 7
		self.amsrc    = 0
		self.static   = 0 
		self.selected = False
		
	def formatCommand(self, param, value):
		return formatCommand(param, self.voice.index, self.index, value)

	def __unicode__(self):
		if self.index != None:
			return str(str(type(self))) + " #" + str(self.index) + " of Voice " + str(self.voice) 
		else:
			return str(type(self)) + " #" + "ALL"


def getID():
	return getStream(cmd_readid)
	
def getIRQueue():
	return getStream(cmd_readirqueue)
	
def formatCommand(paramNum, voiceno, opno, payload, voicemode = 1):
	if type(payload) == list or type(payload) == np.ndarray :
		logger.debug("preparing (" + str(voiceno) + ":" + str(opno) + ") " + cmdNum2Name[paramNum] + " len " + str(len(payload)) + " : "  + str(payload[0:8]))
		payload = np.array(payload, dtype=np.int)
		payload = payload.byteswap().tobytes()
	else:
		logger.debug("preparing (" + str(voiceno) + ":" + str(opno) + ") " + cmdNum2Name[paramNum] + " " + str(payload))
		payload = struct.pack(">I", int(payload))
	payload_array = [paramNum, 1 << opno, (voicemode << 7) | (voiceno >> 8), voiceno] + [int(i) for i in payload] 
	#logger.debug([hex(p) for p in payload_array])
	return payload_array
	
if __name__ == "__main__":
	fpga_interface_inst = fpga_interface()
	
	#for voiceno in range(fpga_interface_inst.POLYPHONYCOUNT):
	#	for opno in range(fpga_interface_inst.OPERATORCOUNT):
	#		for command in fpga_interface_inst.cmdName2number.keys():
	#			fpga_interface_inst.formatCommand(command, opno, voiceno, 0)
				
	# run testbench
	
	logger = logging.getLogger('DT01')
	#formatter = logging.Formatter('{"debug": %(asctime)s {%(pathname)s:%(lineno)d} %(message)s}')
	formatter = logging.Formatter('{{%(pathname)s:%(lineno)d %(message)s}')
	ch = logging.StreamHandler()
	ch.setFormatter(formatter)
	logger.addHandler(ch)
	logger.setLevel(1)
		
	
	def bitrev(n):
		return n
		return int('{:08b}'.format(n)[::-1], 2)
	
	for i in range(1):
		print([hex(bitrev(a)) for a in fpga_interface_inst.getID()])
		#print([hex(bitrev(a)) for a in fpga_interface_inst.getStream(cmd_readaudio)])
		#print([hex(bitrev(a)) for a in fpga_interface_inst.getID()])
		#print([hex(bitrev(a)) for a in fpga_interface_inst.getStream(cmd_readaudio)])
	
	fpga_interface_inst.formatCommand("cmd_env_clkdiv", 0, 0, 0)
	
	opno = 0
	voiceno = 0
	fpga_interface_inst.formatCommand("cmd_channelgain_right", opno, voiceno, 2**16)
	fpga_interface_inst.formatCommand("cmd_gain_rate"      , opno, voiceno, 2**16)
	fpga_interface_inst.formatCommand("cmd_gain"            , opno, voiceno, 2**16)
	fpga_interface_inst.formatCommand("cmd_increment_rate" , opno, voiceno, 2**12)
	fpga_interface_inst.formatCommand("cmd_increment"       , opno, voiceno, 2**22)
	fpga_interface_inst.formatCommand("cmd_fm_algo"       , opno, voiceno, 1)

	opno = 1
	fpga_interface_inst.formatCommand("cmd_increment_rate", opno, voiceno, 2**30)
	fpga_interface_inst.formatCommand("cmd_increment"      , opno, voiceno, 2**22)
	fpga_interface_inst.formatCommand("cmd_fm_algo"      , opno, voiceno, 2)
	
	fpga_interface_inst.formatCommand("cmd_flushspi", 0, 0, 0)
	fpga_interface_inst.formatCommand("cmd_shift"   , 0, 0, 0)
		