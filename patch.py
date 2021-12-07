import struct
from bitarray import bitarray
import logging
import RPi.GPIO as GPIO
from ilock import ILock
import json
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
import dt01
import logging
import collections
import math
import threading
from multiprocessing import Process
#from multiprocessing import shared_memory
import RPi.GPIO as GPIO
logger = logging.getLogger('DT01')
	
MIDINOTES      = 128
CONTROLCOUNT   = 128

def noteToFreq(note):
	a = 440.0 #frequency of A (coomon value is 440Hz)
	return (a / 32) * (2 ** ((note - 9) / 12.0))

class Note:
	def __init__(self, index):
		self.index  = index
		self.voices = []
		self.velocity = 0
		self.velocityReal = 0
		self.held  = False
		self.polytouch = 0
		self.msg  = None
		self.defaultIncrement = 2**32 * (noteToFreq(index) / 96000.0)
		
# patch holds all state, including note and control state
class Patch():
					
	def formatAndSend(self, param, value):
		dt01.formatAndSend(param, 0, 0, value)
	
	def processControl(self, paramName, value):
		self.midi2commands(mido.Message('control_change', control = dt01.controlNum2Num [paramName], value = value)) #
		
	def __init__(self, dt01_inst):
		logger.debug("patch init ")
		self.dt01_inst = dt01_inst
		self.polyphony = 64
		self.active = True
		self.voicesPerNote = 1
		self.voices = []
		self.currVoiceIndex = 0
		self.currVoice = 0
		self.pitchwheel  = 8192
		self.pitchwheelReal  = 1
		self.aftertouch = 0
		self.aftertouchReal = 0
		self.sustain = False
		self.toRelease = [False]*MIDINOTES
		self.allNotes = []
		
		self.computedState = np.zeros((128, self.polyphony, dt01.OPERATORCOUNT)) # fpga cmd, voice, operator
		for i in range(MIDINOTES):
			self.allNotes+= [Note(i)]
			
		self.activeOperator = 0
		self.voices = dt01_inst.getVoices()

		self.allChildren = self.voices
	
		for voice in self.voices:
			#logger.debug("claimed: " + str(voice.index))
			voice.note  = self.allNotes[0]
			voice.patch = self
				
	
		self.control = [0]*CONTROLCOUNT
		
		# set default control values
		self.control[dt01.ctrl_vibrato_env     ] = 0   #
		self.control[dt01.ctrl_tremolo_env     ] = 0   #
		self.control[dt01.ctrl_fbgain          ] = 0  
		self.control[dt01.ctrl_fbsrc           ] = 0  
		self.control[dt01.ctrl_expression      ] = 0   # common midi control
		
		self.control[dt01.ctrl_env             ] = 0 #
		self.control[dt01.ctrl_env_rate       ] = 64  #
		self.control[dt01.ctrl_envexp          ] = 0   #
		self.control[dt01.ctrl_increment       ] = 64  #
		self.control[dt01.ctrl_increment_rate ] = 0   #
		self.control[dt01.ctrl_incexp          ] = 0   #
		self.control[dt01.ctrl_fmsrc           ] = 7   #fm off
		self.control[dt01.ctrl_amsrc           ] = 0   #am off
		self.control[dt01.ctrl_static          ] = 0   #
		self.control[dt01.ctrl_sounding        ] = 0   #
		
		self.control[dt01.ctrl_sustain         ] = 0  # common midi control
		self.control[dt01.ctrl_ratemento      ] = 127  # common midi control
		self.control[dt01.ctrl_filter_resonance] = 0  # common midi control
		self.control[dt01.ctrl_filter_cutoff   ] = 0  # common midi control
		
		self.control[dt01.ctrl_env_clkdiv      ] = 8  #   
		self.control[dt01.ctrl_flushspi        ] = 0   #   
		self.control[dt01.ctrl_passthrough     ] = 0   #   
		self.control[dt01.ctrl_shift           ] = 0   #   
		
		
		self.controlReal = np.zeros((CONTROLCOUNT))

		# establish defaults
		self.controlNum2Val = np.zeros((CONTROLCOUNT))
		self.controlNum2Real= np.zeros((CONTROLCOUNT))
		
		self.opControlNum2Val = np.zeros((dt01.OPERATORCOUNT, CONTROLCOUNT))
		self.opControlNum2Real= np.zeros((dt01.OPERATORCOUNT, CONTROLCOUNT))
		
		# more defaults : should be programmable by patch
		self.phaseCount = 4
		self.envelopeLevel= np.zeros((dt01.OPERATORCOUNT, self.phaseCount))
		self.envelopeLevel[0] = np.array([2**12, 2**11, 0, 0])
		#self.envelopeLevel = np.array([2**12, 2**11, 0, 0]) * np.ones((4, dt01.OPERATORCOUNT))
		#logger.debug(self.envelopeLevel)
		self.envelopeRate  = np.ones((dt01.OPERATORCOUNT, self.phaseCount)) * 2**5
		self.envelopeExp   = np.ones((dt01.OPERATORCOUNT, self.phaseCount))
		self.envelopePhase = np.zeros((len(self.voices), dt01.OPERATORCOUNT), dtype=np.int)
		self.baseEnv = np.zeros((len(self.voices), dt01.OPERATORCOUNT), dtype=np.float)
		
		#			
		#self.midi2commands(mido.Message('pitchwheel', pitch = 64))
		#self.midi2commands(mido.Message('aftertouch', value = 0))
		#for note in self.allNotes:
		#	self.midi2commands(mido.Message('polytouch', note = note.index, value = 0))
		#	
		
		# doesnt belong here
		self.midi2commands(mido.Message('control_change', control = dt01.ctrl_opno    , value = 0)) #
		self.midi2commands(mido.Message('control_change', control = dt01.ctrl_env     , value = 127)) #
		self.midi2commands(mido.Message('control_change', control = dt01.ctrl_opno    , value = 1)) #
		self.midi2commands(mido.Message('control_change', control = dt01.ctrl_env     , value = 2)) #
		
		self.midi2commands(mido.Message('control_change', control = dt01.ctrl_opno      , value = 6)) #
		self.midi2commands(mido.Message('control_change', control = dt01.ctrl_increment , value = 16)) #
		self.midi2commands(mido.Message('control_change', control = dt01.ctrl_opno      , value = 7)) #
		self.midi2commands(mido.Message('control_change', control = dt01.ctrl_increment , value = 16)) #
		
		
		#p = threading.Thread(target=irqueue.envServiceProc, args=())
		#p.start()
		#os.system("python3 irqueue.py &")
			
	def getCurrOpParam2Real(self, index, paramNum):
		return self.controlNum2Real[index,paramNum]
		
	def getCurrOpParam2Val(self, index, paramNum):
		return self.controlNum2Val[index,paramNum]
	
	def setEnv(self, operator, release=False):
		if operator.index < 6:
			#logger.debug("opno" + str(operator.index) + " velo: " + str(operator.voice.note.velocityReal) + ", ocn2r: " + str( self.opControlNum2Real[:,dt01.ctrl_env]))
			self.baseEnv[operator.voice.index, operator.index] = (1 - operator.voice.note.index/256 ) * operator.voice.note.velocityReal * self.opControlNum2Real[operator.index,dt01.ctrl_env]
		elif operator.index == 6:           
			self.baseEnv[operator.voice.index, operator.index] = self.opControlNum2Real[operator.index,dt01.ctrl_env]
		elif operator.index == 7:           
			self.baseEnv[operator.voice.index, operator.index] = self.opControlNum2Real[operator.index,dt01.ctrl_env]
		
	
	def setIncrement(self, operator):
		if operator.index < 6:
			self.computedState[dt01.cmd_increment, operator.voice.index, operator.index] = self.pitchwheelReal * (1 + self.aftertouchReal) * operator.voice.note.defaultIncrement
		elif operator.index == 6:
			self.computedState[dt01.cmd_increment, operator.voice.index, operator.index] = 2**14 * self.opControlNum2Real[operator.index,dt01.ctrl_increment] # * self.getCurrOpParam2Real(operator.index, dt01.increment)
		elif operator.index == 7:
			self.computedState[dt01.cmd_increment, operator.voice.index, operator.index] = 2**12 * self.opControlNum2Real[operator.index,dt01.ctrl_increment] # * self.getCurrOpParam2Real(operator.index, dt01.increment)

	def setPhaseAllOps(self, voiceindex, phase):
		dt01.formatAndSend(dt01.cmd_env_rate, voiceindex, 0, [0]* dt01.OPERATORCOUNT , voicemode=False)                               
		dt01.formatAndSend(dt01.cmd_envexp,   voiceindex, 0, self.envelopeExp  [:,phase], voicemode=False)                           
		dt01.formatAndSend(dt01.cmd_env,      voiceindex, 0, self.baseEnv[voiceindex,:]*self.envelopeLevel[:,phase], voicemode=False)
		dt01.formatAndSend(dt01.cmd_env_rate, voiceindex, 0, self.envelopeRate [:,phase], voicemode=False)                           
		self.envelopePhase[voiceindex, :] = phase
		
		logger.debug("sent env " + str(self.baseEnv[voiceindex,:]*self.envelopeLevel[:,phase]))
		logger.debug("sent rate " + str(self.envelopeRate [:][phase]))
		logger.debug(self.baseEnv[voiceindex,:])
		logger.debug(self.envelopeLevel[:,phase])
		return 0
	
	def processIRQueue(self, 
voiceno, opno):
			currPhase = self.envelopePhase[voiceno, opno]
				
			logger.debug("proc IRQUEUE! voice:" + str(voiceno) + " op:"+ str(opno) + " phase:" + str(currPhase))

			if currPhase >= self.phaseCount - 1:
				logger.debug("STOP PHASE")
			else:
				self.setPhaseAllOps(voiceno, opno)
	
	def midi2commands(self, msg):
	
		commands = []
		logger.debug("\n\nProcessing " + str(msg))
			
		if msg.type == "note_off" or (msg.type == "note_on" and msg.velocity == 0):
			if self.sustain:
				self.toRelease[msg.note] = True
				return
				
			note = self.allNotes[msg.note] 
			note.velocity = 0 
			note.velocityReal = 0 
			voicesToUpdate = note.voices.copy()
			for voice in note.voices:
				voice.spawntime = 0
				for op in voice.operators:
					self.setEnv(op)
				self.setPhaseAllOps(voice.index, 3)
			note.voices = []
			note.held = False
		
		# if note on, spawn voices
		if msg.type == "note_on":
			note = self.allNotes[msg.note]
			note.velocity     = msg.velocity
			note.velocityReal = msg.velocity/127.0
			note.held = True
			note.msg = msg
			# spawn some voices!
			for voiceNoInCluster in range(self.voicesPerNote):
				
				#self.currVoiceIndex = (self.currVoiceIndex + 1) % self.polyphony
				#logger.debug([s.spawntime for s in self.voices])
				voice = sorted(self.voices, key=lambda x: x.spawntime)[0]
				voice.spawntime = time.time()
				voice.indexInCluser = voiceNoInCluster
				voice.note = note
				note.voices += [voice]

				for operator in voice.operators:
					self.setIncrement(operator)
					self.setEnv(operator)
				dt01.formatAndSend(dt01.cmd_increment, voice.index, 0, self.computedState[dt01.cmd_increment,voice.index,:], voicemode = False)
				self.setPhaseAllOps(voice.index, 0)
						
				#dt01.formatAndSend(dt01.cmd_env,       voice.index, 0, self.computedState[dt01.cmd_env,voice.index,:]      , voicemode = False)
				
		if msg.type == 'pitchwheel':
			logger.debug("PW: " + str(msg.pitch))
			self.pitchwheel = msg.pitch
			ARTIPHON = 1
			if ARTIPHON:
				self.pitchwheel *= 2
			amountchange = self.pitchwheel / 8192.0
			self.pitchwheelReal = pow(2, amountchange)
			logger.debug("PWREAL " + str(self.pitchwheelReal))
			
			for voice in self.voices:
				for operator in voice.operators:
					self.setIncrement(operator)
			dt01.formatAndSend(dt01.cmd_increment, 0, 0, self.computedState[dt01.cmd_increment,:,:], voicemode = False)
				
		elif msg.type == 'control_change':
			
			self.control[msg.control]     = msg.value
			self.controlReal[msg.control] = msg.value/127.0
			
			logger.debug("control : " + str(msg.control) + " (" + dt01.controlNum2Name[msg.control] +  "): " + str(msg.value))

			event = "control[" + str(msg.control) + "]"
			
			# patch stores control vals for each operator
			self.controlNum2Val [msg.control] = msg.value
			self.controlNum2Real[msg.control] = msg.value/127.0
			
			# selection
			if msg.control == dt01.ctrl_opno:
				self.activeOperator = min(msg.value, 7)
				#logger.debug(self.activeOperator)
				
			self.opControlNum2Val [self.activeOperator,msg.control] = msg.value
			self.opControlNum2Real[self.activeOperator,msg.control] = msg.value/127.0
			logger.debug("Setting op " + str(self.activeOperator) + " control: " + str(msg.control) + " value: " + str(msg.value/127.0))
			
			# forward some controls
			# PUT THIS BACK
			
			#if msg.control == 0:
			#	self.midi2commands(mido.Message('control_change', control= dt01.ctrl_opno      ], value = 6 ))
			#	self.midi2commands(mido.Message('control_change', control= dt01.ctrl_env      ], value = msg.value ))
			#if msg.control == 1:
			#	self.midi2commands(mido.Message('control_change', control= dt01.ctrl_opno      ], value = 7 ))
			#	self.midi2commands(mido.Message('control_change', control= dt01.ctrl_env      ], value = msg.value ))
			
			# route control3 to control 7 because sometimes 3 is volume control
			if msg.control == 3:
				self.midi2commands(mido.Message('control_change', control= 7, value = msg.value ))
				
			if msg.control == dt01.ctrl_env_clkdiv:
				logger.debug(" setting envclkc div " + str(self.controlNum2Val[dt01.ctrl_env_clkdiv]))
				[self.formatAndSend(dt01.cmd_env_clkdiv , self.controlNum2Val[dt01.ctrl_env_clkdiv])]
				
			if msg.control == dt01.ctrl_flushspi:
				[self.formatAndSend(dt01.cmd_flushspi, self.controlNum2Val[dt01.ctrl_flushspi])]
				
			if msg.control == dt01.ctrl_passthrough:
				[self.formatAndSend(dt01.cmd_passthrough, self.controlNum2Val[dt01.ctrl_passthrough])]
				
			if msg.control == dt01.ctrl_shift:
				[self.formatAndSend(dt01.cmd_shift , self.controlNum2Val[dt01.ctrl_shift])]
				
				
			if msg.control == dt01.ctrl_tremolo_env:
				self.midi2commands(mido.Message('control_change', control = dt01.ctrl_opno, value = 6)) #
				self.midi2commands(mido.Message('control_change', control = dt01.ctrl_env, value = msg.value)) #
				
			if msg.control == dt01.ctrl_vibrato_env:
				self.midi2commands(mido.Message('control_change', control = dt01.ctrl_opno, value = 7)) #
				self.midi2commands(mido.Message('control_change', control = dt01.ctrl_env, value = msg.value)) #
		
			if msg.control == dt01.ctrl_env: 
				# sounding operators begin on note_on
				logger.debug("\n\n-------CTRL_ENV---------\n\n")
				
			for voice in self.voices:
			
				# OPERATOR CONCERNS
				# get active operator
				if self.activeOperator < 2:
					channel  = voice.channels[self.activeOperator]
				activeOperator = voice.operators[self.activeOperator]
				
				if msg.control == dt01.ctrl_voicegain or msg.control == dt01.ctrl_pan : 
					baseVolume = 2**16*self.controlNum2Real["ctrl_voicegain"]
					if self.activeOperator == 0:
						[channel.formatAndSend(dt01.cmd_channelgain, baseVolume*self.controlNum2Real["ctrl_pan"])] # assume 2 channels]
					else:
						#logger.debug(self.controlReal[10])
						[channel.formatAndSend(dt01.cmd_channelgain, baseVolume*(1 - self.controlNum2Real["ctrl_pan"]))] # assume 2 channels]
	
				# FM Algo
				if msg.control == dt01.ctrl_fmsrc:
					activeOperator.fmsrc = msg.value
					formatAndSendVal = 0
					for i in reversed(range(dt01.OPERATORCOUNT)):
						formatAndSendVal = int(formatAndSendVal) << int(math.log2(dt01.OPERATORCOUNT))
						formatAndSendVal += int(voice.operators[i].fmsrc)
						#logger.debug(bin(formatAndSendVal))
					voice.formatAndSend(dt01.cmd_fm_algo, formatAndSendVal)
				
				#am algo
				if msg.control == dt01.ctrl_amsrc:
					formatAndSendVal = 0
					for i in reversed(range(dt01.OPERATORCOUNT)):
						formatAndSendVal = int(formatAndSendVal) << int(math.log2(dt01.OPERATORCOUNT))
						formatAndSendVal += int(voice.operators[i].amsrc)
						#logger.debug(bin(formatAndSendVal))
					voice.formatAndSend(dt01.cmd_am_algo, formatAndSendVal)
					
				if msg.control == dt01.ctrl_fbgain:
					voice.formatAndSend(dt01.cmd_fbgain   , 2**16 * self.controlNum2Real[dt01.ctrl_fbgain]  )
					
				if msg.control == dt01.ctrl_fbsrc:
					voice.formatAndSend(dt01.cmd_fbsrc    , self.controlNum2Val[dt01.ctrl_fbsrc]   )
		
				if msg.control == dt01.ctrl_sounding: 
					activeOperator.sounding = msg.value
					formatAndSendVal = 0
					for i in reversed(range(dt01.OPERATORCOUNT)):
						formatAndSendVal = int(formatAndSendVal) << 1
						formatAndSendVal += int(voice.operators[i].sounding)
						#logger.debug(bin(formatAndSendVal))
					voice.formatAndSend(dt01.cmd_sounding, formatAndSendVal)
					
				if msg.control == dt01.ctrl_static: 
					activeOperator.static = msg.value
					formatAndSendVal = 0
					for i in reversed(range(dt01.OPERATORCOUNT)):
						formatAndSendVal = int(formatAndSendVal) << 1
						formatAndSendVal += int(voice.operators[i].static)
					voice.formatAndSend(dt01.cmd_static, formatAndSendVal)
		
				if msg.control == dt01.ctrl_env: 
					pass
					# sounding operators begin on note_on
					#self.setEnv(activeOperator)
					#dt01.formatAndSend(dt01.cmd_env, activeOperator.index, activeOperator.voice.index, self.computedState[dt01.cmd_env,activeOperator.voice.index,activeOperator.index])
				
						
				if msg.control == dt01.ctrl_env_rate: 
					activeOperator.formatAndSend(dt01.cmd_env_rate      , 2**10 * (1 - self.opControlNum2Real[activeOperator.index,dt01.ctrl_env_rate]) * (1 - self.controlNum2Real[dt01.ctrl_ratemento]) )
		# static oscillators do not have velocity-dependant env
					
				if msg.control == dt01.ctrl_increment:
					self.setIncrement(activeOperator)
					
				if msg.control == dt01.ctrl_increment_rate: 
					activeOperator.formatAndSend(dt01.cmd_increment_rate, 2**10 * (1 - self.controlNum2Real[dt01.ctrl_ratemento]) * (1 - self.controlNum2Real[activeOperator.index,dt01.ctrl_increment_rate]))
					
				if msg.control == dt01.ctrl_incexp: 
					activeOperator.formatAndSend(dt01.cmd_incexp         , self.opControlNum2Val[self.activeOperator,dt01.ctrl_incexp])  
					
				if msg.control == dt01.ctrl_envexp: 
					activeOperator.formatAndSend(dt01.cmd_envexp         , self.opControlNum2Val[self.activeOperator,dt01.ctrl_envexp])
					
					
				if msg.control == dt01.ctrl_sustain: 
					self.sustain  = msg.value
					if not self.sustain:
						for note, release in enumerate(self.toRelease):
							if release:
								self.midi2commands(mido.Message('note_off', note = note, velocity = 0))
						self.toRelease = [False]*MIDINOTES
					
				
			
		elif msg.type == 'polytouch':
			self.polytouch = msg.value
			self.polytouchReal = msg.value/127.0
				
		elif msg.type == 'aftertouch':
			self.aftertouch = msg.value
			self.aftertouchReal = msg.value/127.0
			
			for voice in self.voices:
				for operator in voice.operators:
					self.setIncrement(operator)
					
			[dt01.formatAndSend(dt01.cmd_increment, 0, 0, self.computedState[dt01.cmd_increment,:,:], voicemode = False)]
				
			
		if msg.type == "note_off" or (msg.type == "note_on" and msg.velocity == 0):
			# implement rising mono rate
			for heldnote in self.allNotes[::-1]:
				if heldnote.held and self.polyphony == self.voicesPerNote :
					self.midi2commands(heldnote.msg)
					break
		
		return commands

if __name__ == "__main__":

	logger = logging.getLogger('DT01')
	#formatter = logging.Formatter('{"debug": %(asctime)s {%(pathname)s:%(lineno)d} %(message)s}')
	formatter = logging.Formatter('{{%(pathname)s:%(lineno)d %(message)s}')
	ch = logging.StreamHandler()
	ch.setFormatter(formatter)
	logger.addHandler(ch)

	logger.setLevel(0)
	logger.debug("initializing from scratch")
	polyphony = 64
	dt01_inst = dt01.DT01(polyphony = polyphony)
	
	logger.debug("\n\nInitializing DT01")
	dt01_inst.initialize()
	
	logger.debug("\n\nInitializing Patch")
	testPatch = Patch(dt01_inst)
	
	logger.debug("\n\nformatAndSending post-patch init")
	#dt01_inst.voices[0].operators[6].formatAndSend(dt01.cmd_env, 2**15)
	#dt01_inst.voices[0].operators[0].formatAndSend(dt01.cmd_env, 2**16)
	
	testPatch.midi2commands(mido.Message('control_change', control = dt01.ctrl_opno, value = 0)) #
	testPatch.midi2commands(mido.Message('control_change', control = dt01.ctrl_sounding, value = 1)) #
	testPatch.midi2commands(mido.Message('control_change', control = dt01.ctrl_env, value = 127)) #
	testPatch.midi2commands(mido.Message('control_change', control = dt01.ctrl_fmsrc, value = 1)) #
	
	testPatch.midi2commands(mido.Message('control_change', control = dt01.ctrl_opno, value = 1)) #
	testPatch.midi2commands(mido.Message('control_change', control = dt01.ctrl_env, value = 127)) #
	
	
	testPatch.midi2commands(mido.Message('note_on', channel=0, note=24, velocity=23, time=0))
	dt01_inst.voices[0].operators[0].formatAndSend(dt01.cmd_env, 2**14)
	
	for i in range(1024):
		testPatch.midi2commands(mido.Message('aftertouch', value = int(i/129))) #
		
	#testPatch.midi2commands(mido.Message('note_on', channel=0, note=28, velocity=23, time=0))
	#testPatch.midi2commands(mido.Message('note_on', channel=0, note=31, velocity=23, time=0))
	#	logger.debug(json.dumps(testPatch.controlNum2Real))
	