#!/bin/env python
# Samuel Jero <sjero@purdue.edu>
# Top-level testing script
import os
import sys
import time
from datetime import datetime
import argparse
import socket

system_home = os.path.dirname(os.path.realpath(__file__))
scripts_path = os.path.abspath(os.path.join(system_home, 'scripts'))
config_path = os.path.abspath(os.path.join(system_home, 'config'))
sys.path.insert(1,scripts_path)
sys.path.insert(0,config_path)
from scripts.test import *
import config


def main(args):
	vms_per_instance = config.controllers_per_instance + 1
	standalone = True
	loop = False
	mode = "w"

	#Parse args
	argp = argparse.ArgumentParser(description='Test Executor')
	argp.add_argument('-p','--port', type=int, default=config.coordinator_port)
	argp.add_argument('-c','--coordinator', type=str)
	argp.add_argument('-i','--instance', type=int, default=0)
	argp.add_argument('-l', '--loop', action='store_true')
	args = vars(argp.parse_args(args[1:]))
	instance = args['instance']
	if args['coordinator'] is not None:
		mode = "a"
		standalone = False
	if args['loop'] is True:
		loop = True
		standalone = False

	print "Running Instance " + str(instance) + "..."
	print "Controller: " + config.controller_type

	#Open Log file
	lg = open(config.logs_loc.format(instance=instance), mode)
	lg.write(str(datetime.today()) + "\n")
	lg.write("Instance: " + str(instance) + "\n")
	lg.write("Controller: " + config.controller_type + "\n")


	#Determine VMs
	mininet = [instance*vms_per_instance + 1]
	controllers = list()
	for i in range(1,vms_per_instance):
		controllers.append(mininet[0] + i)
	lg.write("Mininet: " + str(mininet) + "\n")
	lg.write("Controllers: " + str(controllers) + "\n")
	lg.flush()
	tester = SDNTester(mininet,controllers,lg)

	#Start VMs
	print "Starting VMs..."
	if tester.startVms() == False:
		return

	#Do Tests
	if standalone:
		print "Stand alone testing..."
		lg.write("Stand alone testing\n")
		standalone_tests(tester)
	elif loop:
		print "Loop testing..."
		lg.write("Loop testing\n")
		infinite_loop(tester)
	else:
		print  "Coordinated testing..."
		lg.write("Coordinated testing\n")
		coordinated_tests(tester, instance, lg,(args['coordinator'], args['port']))

	#Stop VMs
	print "Stopping VMs..."
	if not loop:
		tester.stopVms()

	#Close log
	lg.write(str(datetime.today()) + "\n")
	lg.close()

def reconnect(addr):
	sock = 0
	while True:
		try:
			sock = socket.create_connection(addr)
			break
		except Exception as e:
			print "[%s] Failed to connect to coordinator (%s:%d): %s...retrying" % (str(datetime.today()),addr[0], addr[1], e)
			time.sleep(5)
			continue
	return sock

#Comments on controller<->executor message format:
# Messages are arbitrary strings ending in \n
# use sock.send() to send and sock.makefile.readline() to receive a full message.
# readline() properly handles waiting for a full message before delivering it. On
# error, an empty string is returned.
# Arbitrary python can be passed back and forth with str=repr(data) and data=eval(str)
def coordinated_tests(tester, instance, lg, addr):
	num = 1

	#Connect
	try:
		sock = socket.create_connection(addr)
	except Exception as e:
		print "[%s] Failed to connect to coordinator (%s:%d): %s" % (str(datetime.today()),addr[0], addr[1], e)
		return
	rf = sock.makefile()

	#Loop Testing Strategies
	baseline_msg = None
	while True:
		print "****************"
		#Ask for Next Strategy
		print "[%s] Asking for Next Strategy..." % (str(datetime.today()))
		lg.write("[%s] Asking for Next Strategy...\n" % (str(datetime.today())))
		try:
			msg = {'msg':'READY','instance':"%s:%d"%(socket.gethostname(),instance)}
			sock.send("%s\n" %(repr(msg)))
		except Exception as e:
			print "Failed to send on socket..."
			rf.close()
			sock.close()
			sock = reconnect(addr)
			rf = sock.makefile()
			continue

		#Get Reply
		try:
			line = rf.readline()
		except Exception as e:
			print "Failed to send on socket..."
			rf.close()
			sock.close()
			sock = reconnect(addr)
			rf = sock.makefile()
			continue
		if line=="":
			rf.close()
			sock.close()
			sock = reconnect(addr)
			rf = sock.makefile()
			continue
		try:
			msg = eval(line)
		except Exception as e:
			continue

		#Check for finished
		if msg['msg']=="DONE":
			#Done, shutdown
			print "[%s] Finished... Shutting down..." % (str(datetime.today()))
			lg.write("[%s] Finished... Shutting down...\n" % (str(datetime.today())))
			break
		elif msg['msg']=="STRATEGY":
			#Test Strategy
			strat = msg['data']
			print "[%s] Test %d: %s" % (str(datetime.today()), num, str(strat))
			lg.write("[%s] Test %d: %s\n" % (str(datetime.today()), num, str(strat)))
			res = tester.doTest(strat)
			# Check if rebaseline is suggested (0=for any metric).
			if res[2] > 0:
				s = "[%s] Rebaseline suggested. Value=%d." % (str(datetime.today()), res[2])
				print s
				lg.write(s + '\n')
				tester.baseline(baseline_msg)
				res = tester.doTest(strat) # Override the previous result.
			num+=1
			
			#Return Result and Feedback
			print "[%s] Test Result: %s, Reason: %s" %(str(datetime.today()),str(res[0]), res[1])
			lg.write("[%s] Test Result: %s , Reason: %s\n" %(str(datetime.today()),str(res[0]), res[1]))

			fb = tester.retrieve_feedback()
			try:
				msg = {'msg':'RESULT','instance':"%s:%d"%(socket.gethostname(),instance), 'value':res[0], 'reason':res[1], 'feedback':fb, 'rebase': res[2]}
				sock.send("%s\n" %(repr(msg)))
			except Exception as e:
				print "Failed to send on socket..."
				sock = reconnect(addr)
				continue
		elif msg['msg'] == 'BASELINE':
			print "[%s] Creating Baseline..." % (str(datetime.today()))
			lg.write("[%s] Creating Baseline...\n" % (str(datetime.today())))
			baseline_msg = msg['test']
			tester.baseline(baseline_msg)

			#Return Feedback
			fb = tester.retrieve_feedback()
			try:
				msg = {'msg':'FEEDBACK','instance':"%s:%d"%(socket.gethostname(),instance), 'data':fb}
				sock.send("%s\n" %(repr(msg)))
			except Exception as e:
				print "Failed to send on socket..."
				sock = reconnect(addr)
				continue
		else:
			print "Unknown Message: %s" % (msg)

	#Cleanup
	rf.close()
	sock.close()

def standalone_tests(tester):
	print "Starting Tests..."
	print "Test 1   " + str(datetime.today())
	res = tester.doTest({'topo':'/root/test1.py','switch':["*,*,*,*,*,CLEAR,*"],'host':None})
	print "Test Result: " + str(res[0])
	print "******"
	print "Test 2   " + str(datetime.today())
	res = tester.doTest({'topo':'/root/test1.py','switch':["{controllers[0]},3,*,of_packet_in,12,CLIE,mfield=12&mval=2&act==&val=1"],'host':None})
	print "Test Result: " + str(res[0])
	print "******"
	print "Test 3   " + str(datetime.today())
	res = tester.doTest({'topo':'/root/test1.py','switch':["*,*,*,*,*,CLEAR,*"],'host':None})
	print "Test Result: " + str(res[0])
	print "******"
	print "Test 4   " + str(datetime.today())
	res = tester.doTest({'topo':'/root/test1.py','switch':["{controllers[0]},3,*,of_packet_in,12,CDIVERT,mfield=12&mval=3&p=100&sw=2&ctl={controllers[0]}","{controllers[0]},2,*,of_packet_in,12,CDIVERT,mfield=12&mval=3&p=100&sw=3&ctl={controllers[0]}"], 'host':None})
	print "Test Result: " + str(res[0])
	print "******"
	print "Test 5   " + str(datetime.today())
	res = tester.doTest({'topo':'/root/test1.py','switch':["{controllers[0]},3,*,of_packet_out,7.1.1,CDIVERT,mfield=7.1.1&mval=2&p=100&sw=1&ctl={controllers[0]}"], 'host':None})
	print "Test Result: " + str(res[0])
	print "******"
	print "Test 6   " + str(datetime.today())
	res = tester.doTest({'topo':'/root/test1.py','switch':None, 'host':[{'cmd':'tunnel','h1':1,'h2':3,'filter':'lldp'},{'cmd':'basic'}]})
	print "Test Result: " + str(res[0])
	print "******"
	print "Test 7   " + str(datetime.today())
        now = str(time.time()+30)
	res = tester.doTest({'topo':'/root/test1.py','switch':None, 'host':[{'cmd':'attack','action':{'module':'arp','command':'inject','type':'is-at','ids':[None,None,None,'vict-ip','mal-mac','vict-ip'],'start':now, 'freq':0.1, 'num':100},'mal':1,'vict':3},{'cmd':'basic'}]})
	print "Test Result: " + str(res[0])
	print "******"
	print "Test 8   " + str(datetime.today())
	res = tester.doTest({'topo':'/root/test1.py','switch':None, 'host':None, 'controller':{'action':'kill','time':45}})
	print "Test Result: " + str(res[0])
	print "******"

def infinite_loop(tester):
	print "Starting Tests..."
	i = 0
	while True:
		print "Test " + str(i) + "   " +  str(datetime.today())
                #Do Nothing
		res = tester.doTest({'topo':'/root/test1.py','switch':["*,*,*,*,*,CLEAR,*"],'host':[{'cmd':'basic'}]})


                #Break Network Quarantine
		#res = tester.doTest({'topo':'/root/test1.py','switch':[{'action':'{controllers[0]},2,*,of_packet_in,3,LIE,act==&val=0','time':20}],'host':None,'controller':[{'action':'kill','time':25}],'priority':100})
                #DeniableDoS
		#res = tester.doTest({'topo':'/root/test1.py','switch':['{controllers[0]},1,*,of_features_reply,11.3.1,LIE,act==&val=65533'],'host':[{'cmd':'attack','action':{'module':'arp','command':'inject','type':'who-has','ids':[None,None,None,None,None,'10.0.0.42'],'freq':0.5,'num':100,'start':time.time()+30},'mal':2},{'cmd':'basic'}],'controller':None,'priority':100})
		#res = tester.doTest({'topo':'/root/test1.py','switch':['{controllers[0]},1,*,of_features_reply,11.3.1,LIE,act==&val=65533'],'host':None,'controller':None,'priority':100})
                #WebServer Impersonation
		#res = tester.doTest({'topo':'/root/test1.py','switch':[{'action':'{controllers[0]},3,*,of_packet_in,*,CDROP,p=100&mfield=12&mval=2','time':40}],'host':[{'cmd':'attack','action':{'module':'arp','command':'inject','type':'is-at','ids':[None,'vict-mac','vict-mac','vict-ip',None,None],'freq':0.1,'num':200,'start':str(time.time()+45)},'mal':1,'vict':3},{'cmd':'hijack'}],'controller':None,'priority':100})
		#res = tester.doTest({'topo':'/root/test1.py','switch':None,'host':[{'cmd':'attack','action':{'module':'arp','command':'inject','type':'is-at','ids':[None,'vict-mac','vict-mac','vict-ip',None,None],'freq':0.1,'num':200,'start':str(time.time()+45)},'mal':1,'vict':3},{'cmd':'hijack'}],'controller':None,'priority':100})


		print "Test Result: " + str(res[0])
		print "******"
		i += 1

if __name__ == "__main__":
	main(sys.argv)
