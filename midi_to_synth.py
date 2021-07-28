import struct
import sys
import numpy as np 
from dt01 import *
import spidev
import time
import rtmidi
from rtmidi.midiutil import *
import mido
import math
import json


def noteToFreq(note):
	a = 440.0 #frequency of A (coomon value is 440Hz)
	return (a / 32) * (2 ** ((note - 9) / 12))

MIDINOTES      = 128
CONTROLCOUNT   = 128

# gotta be global
noteno = 0

class MidiInputHandler(object):
	def loadPatch(patchFilename):
		with open(patchFilename) as f:
			return json.loads(f.read())
		
	def __init__(self, port):

		TCP_IP = '127.0.0.1'
		TCP_PORT = 5000 + port
		BUFFER_SIZE = 50  # Normally 1024, but we want fast response

		self.s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
		self.s.bind((TCP_IP, TCP_PORT))
		self.s.setBlocking(False)
	
		patchFilename = os.path.join(sys.path[0], "patches/Classic/default.json")
		self.patch = self.loadPatch(patchFilename)
		self.port  = port
		self._wallclock  = time.time() 
		self.increment   = np.zeros((POLYPHONYCOUNT, OPERATORCOUNT))
		self.heldNotes   = -np.ones((MIDINOTES), dtype=int)
		self.voice2note  = -np.ones((POLYPHONYCOUNT), dtype=int)
		self.controlVals = np.zeros((CONTROLCOUNT), dtype=int)
		self.pitchWheel  = 0.5
		self.afterTouch  = 0.0
		self.toRelease   = []
		self.mastergain_right_spawn = 2**16
		self.mastergain_left_spawn  = 2**16
		self.o1ratio = 1
		self.hold = 0
	
	def updateOperator(self):
		
	def updateVoice(self):
	
	def updateHeldNotes(self):
		
	
	def routine_noteoff(self, message):
		if self.hold > 64:
			self.toRelease += [message]
			return
	
		self.gainporta = 100
		self.voicegain = 0
		for voice, note in enumerate(voice2note):
			if message.note == note
				#print(note)
				spi.xfer2( format_command_int(cmd_gain_porta	 , 0, note, self.patch["volume_porta"][-1]))
				spi.xfer2( format_command_int(cmd_gain			 , 0, note, self.patch["volume"][-1])
				spi.xfer2( format_command_int(cmd_increment_porta, 0, note, self.patch["pitch_porta"][-1]))
				spi.xfer2( format_command_int(cmd_increment      , 0, note, self.patch["pitch"][-1]))
				
				# if a note is still held, and mono mode, drop to highest held note
				if any(self.heldNotes + 1) and POLYPHONYCOUNT == 1: 
					message.note     = np.max(np.where(self.heldNotes))
					message.velocity = self.velocitylast
					self.routine_noteon(message)
				# otherwise, just remove it
				else:
					self.voice2note[voice] = -1
					self.heldNotes[note] = -1
			
				
		

	def routine_noteon(self, message):
		global noteno
		self.voicegain = int(2**16 * math.pow(message.velocity/128.0, 1/4.0))
		self.gainporta = 1
		self.velocitylast  = message.velocity
		thisinc = int(2**32  * noteToFreq(message.note) / 96000)
		self.increment[noteno][0] = thisinc
		self.incporta  = 2**16
			
		spi.xfer2( format_command_int(cmd_gain_porta	 , 0, note, self.patch["volume_porta"][0]))
		spi.xfer2( format_command_int(cmd_gain			 , 0, note, self.patch["volume"][0])
		spi.xfer2( format_command_int(cmd_increment_porta, 0, note, self.patch["pitch_porta"][0]))
		spi.xfer2( format_command_int(cmd_increment      , 0, note, self.patch["pitch"][0]))
		spi.xfer2( format_command_int(cmd_fmmod_selector , 0, noteno, 1))
		spi.xfer2( format_command_int(cmd_fmdepth        , 0, noteno, self.fmdepth_spawn))
		
		
		spi.xfer2( format_command_int(cmd_increment_porta, 1, noteno, self.incporta))
		spi.xfer2( format_command_int(cmd_increment		 , 1, noteno, thisinc * self.pitchWheel * self.o1ratio))
		spi.xfer2( format_command_int(cmd_fmmod_selector , 1, noteno, 2))
		
		spi.xfer2( format_command_int(cmd_mastergain_left,  0, noteno, self.mastergain_left_spawn ))
		spi.xfer2( format_command_int(cmd_mastergain_right, 0, noteno, self.mastergain_right_spawn))
		
		self.heldNotes[message.note] = int(noteno)
		noteno= (noteno+ 1) % POLYPHONYCOUNT
	
	def __call__(self, event, data=None):
		message, deltatime = event
		print(message)
		self._wallclock += deltatime
		#print("[%s] @%0.6f %r" % (self.port, self._wallclock, message))
		#print(message)
		message = mido.Message.from_bytes(message)
		#print(message.type)
		if message.type == 'note_on':
			if message.velocity == 0:
				self.routine_noteoff(message)
			else:
				self.routine_noteon(message)
				
		elif message.type == 'note_off':
			self.routine_noteoff(message)
			
		elif message.type == 'pitchwheel':
			print("PW: " + str(message.pitch))
			amountchange = message.pitch / 8192.0
			amountchange = pow(2, amountchange)
			
			self.pitchWheel = amountchange
			for i in self.heldNotes:
				if i != -1:
					spi.xfer2( format_command_int(cmd_increment, 0, int(i), self.increment[int(i)][0]*amountchange))
				
		
		elif message.type == 'aftertouch':
			amountchange = message.value / 128.0
			amountchange = pow(1.5, amountchange)
			
			self.pitchWheel = amountchange
			for i in self.heldNotes:
				if i != -1:
					spi.xfer2( format_command_int(cmd_increment, 0, int(i), self.increment[int(i)][0]*amountchange))
				
		
		elif message.is_cc():
			print('Control change message received: ' + str(message.control))
			if message.control == 1:
				print(message.value)
				for i, noteno in enumerate(self.heldNotes):
					if noteno >= 0:
						self.fmdepth_spawn = int(2**14*(message.value/128.0))
						cmd = format_command_int(cmd_fmdepth, 0, int(noteno), int(self.fmdepth_spawn))
						spi.xfer2(cmd)
			elif message.control == 12:
				for voice in range(POLYPHONYCOUNT):
					spi.xfer2( format_command_int(cmd_gain, 0, voice, 0 ))
					
			#	spi.xfer2( format_command_int(cmd_shift, 0, 0, message.value))
			elif message.control == 13:
				self.mastergain_right_spawn = 2**16*(message.value/128.0)
			elif message.control == 14:
				self.mastergain_left_spawn = 2**16*(message.value/128.0)
			elif message.control == 15:
				print(message.value)
				for i, noteno in enumerate(self.heldNotes):
					if noteno >= 0:
						self.o1ratio = (8 / (message.value))
						freq = self.increment[int(noteno)][0]*self.pitchWheel*self.o1ratio
						spi.xfer2( format_command_int(cmd_increment, 1, int(noteno), freq))
				
			elif message.control == 64: # sustain pedal
				self.hold = message.value
				if self.hold < 64:
					for release in self.toRelease:
						self.routine_noteoff(release)
					self.toRelease = []
			

		#spi.xfer2( format_command_int(cmd_increment_adj	, noteno, 0))
		#spi.xfer2( format_command_int(cmd_mod_selector	 , noteno, 0))
		
	

if __name__ == "__main__":

	spi = spidev.SpiDev()

	spi.open(1, 0)
	spi.max_speed_hz=maxSpiSpeed

		
	port = sys.argv[1] if len(sys.argv) > 1 else None
	api=rtmidi.API_UNSPECIFIED
	midiDev = []
	midiin = rtmidi.MidiIn(get_api_from_environment(api))
	ports  = midiin.get_ports()
	print(ports)
	for port in ports:
		try:
			midiin, port_name = open_midiinput(port)
			midiDev += [midiin]
		except (EOFError, KeyboardInterrupt):
			sys.exit()


		print("Attaching MIDI input callback handler.")
		midiin.set_callback(MidiInputHandler(port_name))

	spi.xfer2( format_command_int(cmd_mastergain_right, 0, 0, 2**16))
	spi.xfer2( format_command_int(cmd_mastergain_left , 0, 0, 2**16))

	spi.xfer2( format_command_int(cmd_flushspi , 0, 0, 1))
	spi.xfer2( format_command_int(cmd_passthrough, 0, 0, 0))
	spi.xfer2( format_command_int(cmd_shift, 0, 0, 4))

	print("Entering main loop. Press Control-C to exit.")
	try:
		# Just wait for keyboard interrupt,
		# everything else is handled via the input callback.
		while True:
			for dev in midiDev:
				data = dev.s.recv(BUFFER_SIZE)
				if len(data):
					dev.loadPatch(data)
			
	except KeyboardInterrupt:
		print('')
	finally:
		print("Exit.")
		midiin.close_port()
		del midiin