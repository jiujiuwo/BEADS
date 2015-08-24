#!/usr/bin/env python
# Samuel Jero <sjero@purdue.edu>
# Testing Script
from mininet.net import Mininet
from mininet.node import UserSwitch, OVSKernelSwitch, Controller, RemoteController
from mininet.node import CPULimitedHost
from mininet.topo import Topo
from mininet.log import lg
from mininet.link import TCLink
from functools import partial
from threeTierTree import ThreeTierTree
from fatTree import FatTree
from fixedTree import FixedTree
from time import time, sleep
from mininet.cli import CLI
from mininet.util import quietRun
from functools import partial
import string
import os
import sys
import re
import time

def waitListening( client=None, server='127.0.0.1', port=80, timeout=None ):
	"""Wait until server is listening on port.
	returns True if server is listening"""
	runCmd = ( client.cmd if client else
	       partial( quietRun, shell=True ) )
	if not runCmd( 'which telnet' ):
		raise Exception('Could not find telnet' )
	# pylint: disable=maybe-no-member
	serverIP = server if isinstance( server, basestring ) else server.IP()
	cmd = ( 'ping -c 1 ' + serverIP)
	result = runCmd( cmd )
	if 'ttl' not in result:
		lg.error( 'Could not connect to %s on port %d\n' % ( server, port ) )
		return False
	cmd = ( 'echo A | telnet -e A %s %s' % ( serverIP, port ) )
	start = time.time()
	result = runCmd( cmd )
	while 'Connected' not in result:
		if 'No route' in result:
			rtable = runCmd( 'route' )
			lg.error( 'no route to %s:\n%s' % ( server, rtable ) )
			return False
		if timeout and time.time() >= start + timeout:
			lg.error( 'could not connect to %s on port %d\n' % ( server, port ) )
			return False
		lg.debug( 'waiting for', server, 'to listen on port', port, '\n' )
		lg.info( '.' )
		time.sleep(0.5)
		result = runCmd( cmd )
	return True

def _parseIperf( iperfOutput ):
	"""Parse iperf output and return bandwidth.
	   iperfOutput: string
	   returns: result string"""
	r = r'([\d\.]+ \w+/sec)'
	m = re.findall( r, iperfOutput )
	if m:
	    return m[-1]
	else:
	    # was: raise Exception(...)
	    lg.error( 'could not parse iperf output: ' + iperfOutput )
	    return ''

def iperf(hosts=None, l4Type='TCP', udpBw='10M', fmt=None,
       seconds=5, port=5001, timeout=2):
	"""Run iperf between two hosts.
	   hosts: list of hosts; if None, uses first and last hosts
	   l4Type: string, one of [ TCP, UDP ]
	   udpBw: bandwidth target for UDP test
	   fmt: iperf format argument if any
	   seconds: iperf time to transmit
	   port: iperf port
	   returns: two-element array of [ server, client ] speeds
	   note: send() is buffered, so client rate can be much higher than
	   the actual transmission rate; on an unloaded system, server
	   rate should be much closer to the actual receive rate"""
	assert len( hosts ) == 2
	client, server = hosts
	lg.output( '*** Iperf: testing', l4Type, 'bandwidth between',
		client, 'and', server, '\n' )
	server.cmd( 'killall -9 iperf' )
	iperfArgs = 'iperf -p %d ' % port
	bwArgs = ''
	if l4Type == 'UDP':
	    iperfArgs += '-u '
	    bwArgs = '-b ' + udpBw + ' '
	elif l4Type != 'TCP':
	    raise Exception( 'Unexpected l4 type: %s' % l4Type )
	if fmt:
	    iperfArgs += '-f %s ' % fmt
	server.sendCmd( iperfArgs + '-s' )
	if l4Type == 'TCP':
	    if not waitListening( client, server.IP(), port, timeout ):
		raise Exception( 'Could not connect to iperf on port %d'
				 % port )
	cliout = client.cmd( iperfArgs + '-t %d -c ' % seconds +
			     server.IP() + ' ' + bwArgs )
	lg.debug( 'Client output: %s\n' % cliout )
	server.sendInt()
	servout = server.waitOutput()
	lg.debug( 'Server output: %s\n' % servout )
	result = [ _parseIperf( servout ), _parseIperf( cliout ) ]
	if l4Type == 'UDP':
	    result.insert( 0, udpBw )
	lg.output( '*** Results: %s\n' % result )
	return result

	#Main
if __name__ == '__main__':
	try:
		#Set Log Level
		lg.setLogLevel( 'info' )
		#lg.setLogLevel( 'error' )

		if len(sys.argv) < 2:
			lg.output("No Controller!\n")
			sys.exit()

		ctlip = list()
		ctlport = list()
		for i in range(1, len(sys.argv)):
			tmp = string.split(sys.argv[i],':')
			if len(tmp) != 2:
				lg.output("Invalid controller format. Expect:  <host:port>")
				sys.exit()
			ctlip.append(tmp[0])
			ctlport.append(int(tmp[1]))

		#Setup Network
		topo = FixedTree(depth=2, fanout=2)
		network = Mininet(topo=topo, controller=None, switch=OVSKernelSwitch)
		for i in range(0, len(ctlip)):
			network.addController('c' + str(i+1), controller=RemoteController, ip=ctlip[i], port=ctlport[i])
		network.start()

		#Wait for topology discovery
		sleep(10)

		results = list()

		#Test 1 -- ping
		lg.output("\n\nTest 1 --- Ping\n")
		res = network.pingAll()
		if res > 0:
			results.append(False)
		else:
			results.append(True)

		#Test 2 -- iperf
		lg.output("\n\nTest 2 --- Iperf\n")
		found = False
		for ha in network.hosts:
			for hb in network.hosts:
				if ha != hb:
					try:
						res = iperf([ha, hb], l4Type = 'TCP', seconds=2)
						if res[0] == 0 or res[1] == 0:
							found = True
							break
					except Exception as e:
						lg.output(str(e) + "\n")
						hb.sendInt()
						os.system("pkill iperf")
						hb.waitOutput()
						found = True
		if found:
			results.append(False)
		else:
			results.append(True)

		#Test 3 -- www
		lg.output("\n\nTest 3 --- WWW\n")
		network.hosts[3].sendCmd("cd /root/web/benign; python -m SimpleHTTPServer 8080")
		network.hosts[1].sendCmd("cd /root/web/evil; python -m SimpleHTTPServer 8080")
		network.hosts[2].sendCmd("cd /root/web/evil; python -m SimpleHTTPServer 8080")
		sleep(1)
		res = network.hosts[0].cmd("curl http://" + network.hosts[3].IP() + ":8080/")
		lg.output(res + "\n")
		if string.find(res, "HTML") > 0 and string.find(res, "Evil") == -1:
			results.append(True)
		else:
			results.append(False)
		network.hosts[1].sendInt()
		network.hosts[2].sendInt()
		network.hosts[3].sendInt()

		print repr(results)
		lg.output(str(results) + "\n")

		#Cleanup Network
		network.stop()
	except Exception as e:
		print repr([False, False, False])
		lg.output(e)
		os.system("mn -c > /dev/null 2>/dev/null")