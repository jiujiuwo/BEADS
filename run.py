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

	#Parse args
	argp = argparse.ArgumentParser(description='Test Executor')
	argp.add_argument('-p','--port', type=int, default=config.coordinator_port)
	argp.add_argument('-c','--coordinator', type=str)
	argp.add_argument('-i','--instance', type=int, default=0)
	args = vars(argp.parse_args(args[1:]))
	instance = args['instance']
	if args['coordinator'] is not None:
		standalone = False

	print "Running Instance " + str(instance) + "..."

	#Open Log file
	lg = open(config.logs_loc.format(instance=instance), "w")
	lg.write(str(datetime.today()) + "\n")
	lg.write("Instance: " + str(instance) + "\n")

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
	tester.startVms()

	#Do Tests
	if standalone:
		standalone_tests(tester)
	else:
		coordinated_tests(tester, instance, lg,(args['coordinator'], args['port']))

	#Stop VMs
	print "Stopping VMs..."
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
def coordinated_tests(tester, instance,lg, addr):
	num = 1

	#Connect
	try:
		sock = socket.create_connection(addr)
	except Exception as e:
		print "[%s] Failed to connect to coordinator (%s:%d): %s" % (str(datetime.today()),addr[0], addr[1], e)
		return
	rf = sock.makefile()

	#Loop Testing Strategies
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
			sock = reconnect(addr)
			continue

		#Get Reply
		line = rf.readline()
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
			res = tester.doTest(strat[0],strat[1])
			num+=1

			#Return Result
			print "[%s] Test Result: %s" %(str(datetime.today()),str(res))
			lg.write("[%s] Test Result: %s\n" %(str(datetime.today()),str(res)))
			try:
				msg = {'msg':'RESULT','instance':"%s:%d"%(socket.gethostname(),instance), 'value':res, 'data':strat}
				sock.send("%s\n" %(repr(msg)))
			except Exception as e:
				print "Failed to send on socket..."
				sock = reconnect(addr)
				continue
		elif msg['msg' == 'BASELINE']:
			print "[%s] Creating Baseline..." % (str(datetime.today()))
			lg.write("[%s] Creating Baseline...\n" % (str(datetime.today())))
			tester.baseline(msg['test'])
		else:
			print "Unknown Message: %s" % (msg)

	#Cleanup
	rf.close()
	sock.close()

def standalone_tests(tester):
	print "Starting Tests..."
	print "Test 1   " + str(datetime.today())
	res = tester.doTest("/root/test2.py {controllers}", ["*,*,*,*,*,CLEAR,*"])
	print "Test Result: " + str(res)
	print "******"
	print "Test 2   " + str(datetime.today())
	res = tester.doTest("/root/test2.py {controllers}", ["{controllers[0]},3,*,of_packet_in,12,CLIE,mfield=12&mval=2&act==&val=1"])
	print "Test Result: " + str(res)
	print "******"
	print "Test 3   " + str(datetime.today())
	res = tester.doTest("/root/test1.py {controllers}", ["*,*,*,*,*,CLEAR,*"])
	print "Test Result: " + str(res)
	print "******"
	print "Test 4   " + str(datetime.today())
	res = tester.doTest("/root/test1.py {controllers}", ["{controllers[0]},3,*,of_packet_in,12,CDIVERT,mfield=12&mval=3&p=100&sw=2&ctl={controllers[0]}","{controllers[0]},2,*,of_packet_in,12,CDIVERT,mfield=12&mval=3&p=100&sw=3&ctl={controllers[0]}"])
	print "Test Result: " + str(res)
	print "******"
	print "Test 5   " + str(datetime.today())
	res = tester.doTest("/root/test1.py {controllers}", ["{controllers[0]},3,*,of_packet_out,7.1.1,CDIVERT,mfield=7.1.1&mval=2&p=100&sw=1&ctl={controllers[0]}"])
	print "Test Result: " + str(res)
	print "******"


if __name__ == "__main__":
	main(sys.argv)
