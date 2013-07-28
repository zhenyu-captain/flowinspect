#!/usr/bin/env python

__author__	= 'Ankur Tyagi (7h3rAm)'
__email__	= '7h3rAm [at] gmail [dot] com'
__version__	= '0.2'
__license__	= 'CC-BY-SA 3.0'
__status__	= 'Development'


import os, sys, shutil, argparse, datetime

try: import nids
except ImportError, ex:
	print '[-] Import failed: %s' % ex
	print '[-] Cannot proceed. Exiting.'
	print
	sys.exit(1)


try:
	import re2 as re
	regexengine = 're2'
except importError, ex:
	import re
	regexengine = 're'

try:
	from pydfa.pydfa import *
	from pydfa.graph import *
	dfaengine = 'pydfa'
except ImportError, ex:
	print '[!] Import failed: %s' % (ex)
	dfaengine = None

try:
	import pylibemu as emu
	shellcodeengine = 'pylibemu'
except ImportError, ex:
	print '[!] Import failed: %s' % (ex)
	shellcodeengine = None


sys.dont_write_bytecode = True
from utils import *


configopts = {
			'name':os.path.basename(sys.argv[0]),
			'version':'0.2',
			'desc':'A tool for network traffic inspection',
			'author':'Ankur Tyagi (7h3rAm) @ Juniper Networks Security Research Group',

			'pcap':None,
			'device':None,
			'livemode':False,

			'ctsregexes':[],
			'stcregexes':[],

			'ctsdfas':{},
			'stcdfas':{},
			'dfaexpression':None,

			'offset':0,
			'depth':0,

			'packetct':0,
			'streamct':0,

			'inspudppacketct':0,
			'insptcppacketct':0,
			'insptcpstreamct':0,

			'disppacketct':0,
			'dispstreamct':0,

			'maxinsppackets':0,
			'maxinspstreams':0,
			'maxdisppackets':0,
			'maxdispstreams':0,
			'maxdispbytes':0,

			'packetmatches':0,
			'streammatches':0,

			'shortestmatch':{ 'packet':0, 'packetid':0, 'stream':0, 'streamid':0 },
			'longestmatch':{ 'packet':0, 'packetid':0, 'stream':0, 'streamid':0 },

			'udpdone':False,
			'tcpdone':False,

			'inspectionmodes':[],

			'reflags':0,
			'igncase':False,
			'multiline':False,

			'bpf':None,
			'invertmatch':False,
			'killtcp':False,
			'verbose':False,
			'graph':False,
			'outmodes':[],
			'logdir':'.',
			'graphdir':'.',
			'writelogs':False,
			'linemode':False,

			'regexengine':None,
			'shellcodeengine':None

			}

matchstats = {
			'addr':None,
			'regex':None,
			'dfaobject':None,
			'dfapattern':None,
			'dfastatecount':0,
			'dfaexpression':None,
			'start':0,
			'end':0,
			'matchsize':0,
			'direction':None,
			'directionflag':None,
			'detectiontype':None,
			'shellcodeoffset':0
			}

openudpflows = {}
opentcpflows = {}


def isudpcts(addr):
	((src, sport), (dst, dport)) = addr

	if dport <= 1024 and sport >= 1024: return True
	else: return False


def handleudp(addr, payload, pkt):
	global configopts, openudpflows, regexengine, shellcodeengine, dfaengine

	showmatch = False
	addrkey = addr
	((src, sport), (dst, dport)) = addr
	count = len(payload)
	start = 0
	end = count
	data = payload

	inspectcts = False
	inspectstc = False
	if len(configopts['ctsregexes']) > 0: inspectcts = True
	if len(configopts['stcregexes']) > 0: inspectstc = True

	if not inspectcts:
		for dfa in configopts['dfas'].keys():
			if configopts['dfas'][dfa]['direction'] == 'CTS' or configopts['dfas'][dfa]['direction'] == 'ANY':
				inspectcts = True

	if not inspectstc:
		for dfa in configopts['dfas'].keys():
			if configopts['dfas'][dfa]['direction'] == 'STC' or configopts['dfas'][dfa]['direction'] == 'ANY':
				inspectstc = True

	if isudpcts(addr):
		if inspectcts or 'shellcode' in configopts['inspectionmodes'] or configopts['linemode']:
			direction = 'CTS'
			directionflag = '>'
			key = '%s:%s' % (src, sport)
			keydst = '%s:%s' % (dst, dport)
		else: return

	else:
		if inspectstc or 'shellcode' in configopts['inspectionmodes'] or configopts['linemode']:
			direction = 'STC'
			directionflag = '<'
			key = '%s:%s' % (dst, dport)
			keydst = '%s:%s' % (src, sport)
		else: return

	if key in openudpflows and openudpflows[key]['keydst'] == keydst:
		openudpflows[key]['totdatasize'] += count
	else:
		configopts['packetct'] += 1
		openudpflows.update({ key:{
										'id':configopts['packetct'],
										'keydst':keydst,
										'matches':0,
										'ctsdatasize':0,
										'stcdatasize':0,
										'totdatasize':count
									}
							})

	if direction == 'CTS': openudpflows[key]['ctsdatasize'] += count
	elif direction == 'STC': openudpflows[key]['stcdatasize'] += count

	if configopts['verbose']:
		print '[DEBUG] handleudp - [UDP#%08d] %s %s %s [%dB] (TRACKED: %d) (CTS: %dB | STC: %dB | TOT: %dB)' % (
				openudpflows[key]['id'],
				key,
				directionflag,
				keydst,
				count,
				len(openudpflows),
				openudpflows[key]['ctsdatasize'],
				openudpflows[key]['stcdatasize'],
				openudpflows[key]['totdatasize'])

	if not configopts['linemode']:
		if configopts['udpdone']:
			if configopts['tcpdone']:
				if configopts['verbose']:
					print '[DEBUG] handleudp - Done inspecting max packets (%d) and max streams (%d), \
							preparing for exit' % (
							configopts['maxinsppackets'],
							configopts['maxinspstreams'])
				exitwithstats()
			else:
				if configopts['verbose']:
					print '[DEBUG] handleudp - Ignoring packet %s:%s - %s:%s (inspudppacketct: %d == maxinsppackets: %d)' % (
							src,
							sport,
							dst,
							dport,
							configopts['inspudppacketct'],
							configopts['maxinsppackets'])
			return

	regexes = []
	dfas = {}
	timestamp = datetime.datetime.fromtimestamp(nids.get_pkt_ts()).strftime('%H:%M:%S | %Y/%m/%d')

	if regexengine:
		for regex in configopts['ctsregexes']:
			regexes.append(regex)
	else: regexes = []

	if dfaengine and 'dfa' in configopts['inspectionmodes']:
		for dfa in configopts['dfas'].keys():
			dfas[dfa] = [ configopts['dfas'][dfa]['direction'], configopts['dfas'][dfa]['dfa'], configopts['dfas'][dfa]['memberid'], configopts['dfas'][dfa]['truthvalue'] ]
	else: dfas = {}

	configopts['inspudppacketct'] += 1

	if configopts['linemode']:
		matchstats['addr'] = addrkey
		matchstats['start'] = start
		matchstats['end'] = end
		matchstats['matchsize'] = matchstats['end'] - matchstats['start']
		matchstats['direction'] = direction
		matchstats['directionflag'] = directionflag
		if configopts['verbose']: print '[DEBUG] handleudp - [UDP#%08d] Skipping inspection as linemode is enabled.' % (
											configopts['packetct'])
		showudpmatches(data[matchstats['start']:matchstats['end']])
		return

	if configopts['maxinsppackets'] != 0 and configopts['inspudppacketct'] >= configopts['maxinsppackets']:
		configopts['udpdone'] = True

	if configopts['offset'] > 0 and configopts['offset'] < count:
		offset = configopts['offset']
	else:
		offset = 0

	if configopts['depth'] > 0 and configopts['depth'] <= (count - offset):
		depth = configopts['depth'] + offset
	else:
		depth = count

	inspdata = data[offset:depth]
	inspdatalen = len(inspdata)

	if configopts['verbose']:
		print '[DEBUG] handleudp - [UDP#%08d] Initiating inspection on %s[%d:%d] - %dB' % (
				configopts['packetct'],
				direction,
				offset,
				depth,
				inspdatalen)

	matched = inspect('UDP', configopts['packetct'], inspdata, inspdatalen, regexes, dfas, addrkey)

	if matched:
		openudpflows[key]['matches'] += 1

		matchstats['start'] += offset
		matchstats['end'] += offset

		matchstats['direction'] = direction
		matchstats['directionflag'] = directionflag

		if configopts['packetmatches'] == 0:
			configopts['shortestmatch']['packet'] = matchstats['matchsize']
			configopts['shortestmatch']['packetid'] = configopts['packetct']
			configopts['longestmatch']['packet'] = matchstats['matchsize']
			configopts['longestmatch']['packetid'] = configopts['packetct']
		else:
			if matchstats['matchsize'] <= configopts['shortestmatch']['packet']:
				configopts['shortestmatch']['packet'] = matchstats['matchsize']
				configopts['shortestmatch']['packetid'] = configopts['packetct']

			if matchstats['matchsize'] >= configopts['longestmatch']['packet']:
				configopts['longestmatch']['packet'] = matchstats['matchsize']
				configopts['longestmatch']['packetid'] = configopts['packetct']

		configopts['packetmatches'] += 1

		matchstats['addr'] = addrkey
		showudpmatches(data[matchstats['start']:matchstats['end']])


def showudpmatches(data):
	global configopts, matchstats

	proto = 'UDP'
	((src, sport), (dst, dport)) = matchstats['addr']

	if configopts['maxdispbytes'] > 0: maxdispbytes = configopts['maxdispbytes']
	else: maxdispbytes = len(data)

	filename = '%s/%s-%08d.%s.%s.%s.%s' % (configopts['logdir'], proto, configopts['packetct'], src, sport, dst, dport)

	if configopts['writelogs']:
		writetofile(proto, configopts['packetct'], src, sport, dst, dport, data)

		if configopts['verbose']:
			print '[DEBUG] showudpmatches - [UDP#%08d] Wrote %dB to %s/%s-%08d.%s.%s.%s.%s' % (
					configopts['packetct'],
					matchstats['matchsize'],
					configopts['logdir'],
					proto,
					configopts['packetct'],
					src,
					sport,
					dst,
					dport)

	if 'quite' in configopts['outmodes']:
		if configopts['verbose']:
			print '[DEBUG] showudpmatches - [UDP#%08d] %s:%s %s %s:%s matches \'%s\' @ [%d:%d] - %dB' % (
					configopts['packetct'],
					src,
					sport,
					matchstats['directionflag'],
					dst,
					dport,
					getregexpattern(matchstats['regex']),
					matchstats['start'],
					matchstats['end'],
					matchstats['matchsize'])
		return

	if configopts['maxdisppackets'] != 0 and configopts['disppacketct'] >= configopts['maxdisppackets']:
		if configopts['verbose']:
			print '[DEBUG] showudpmatches - Skipping outmode parsing (disppacketct: %d == maxdisppackets: %d)' % (
					configopts['disppacketct'],
					configopts['maxdisppackets'])
		return

	if 'meta' in configopts['outmodes']:
		if matchstats['detectiontype'] == 'regex':
			metastr = 'matches regex: \'%s\'' % (getregexpattern(matchstats['regex']))
		elif matchstats['detectiontype'] == 'dfa':
			metastr = 'matches dfa: \'%s\' (State Count: %d)' % (matchstats['dfapattern'], matchstats['dfastatecount'])
		elif matchstats['detectiontype'] == 'shellcode':
			metastr = 'contains shellcode (Offset: %d)' % (matchstats['shellcodeoffset'])
		else:
			metastr = ''

		print '[MATCH] (%08d/%08d) [UDP#%08d] %s:%s %s %s:%s %s' % (
				configopts['inspudppacketct'],
				configopts['packetmatches'],
				configopts['packetct'],
				src,
				sport,
				matchstats['directionflag'],
				dst,
				dport,
				metastr)

		print '[MATCH] (%08d/%08d) [UDP#%08d] match @ %s[%d:%d] - %dB' % (
				configopts['inspudppacketct'],
				configopts['packetmatches'],
				configopts['packetct'],
				matchstats['direction'],
				matchstats['start'],
				matchstats['end'],
				matchstats['matchsize'])

	if 'print' in configopts['outmodes']: printable(data[:maxdispbytes])
	if 'raw' in configopts['outmodes']: print data[:maxdispbytes]
	if 'hex' in configopts['outmodes']: hexdump(data[:maxdispbytes])

	configopts['disppacketct'] += 1


def inspect(proto, data, datalen, regexes, dfas, addrkey, direction):
	global configopts, opentcpflows, openudpflows,  matchstats, regexengine, shellcodeengine, dfaengine

	skip = False
	matched = False
	partialmatch = False
	finalmatch = False
	((src, sport), (dst, dport)) = addrkey

	if proto == 'TCP':
		id = opentcpflows[addrkey]['id']
		openflows = opentcpflows
	elif proto == 'UDP':
		id = openudpflows[addrkey]['id']
		openflows = openudpflows

	if configopts['verbose']:
		print '[DEBUG] inspect - [%s#%08d] Received %dB for inspection from %s:%s - %s:%s' % (
				proto,
				id,
				datalen,
				src,
				sport,
				dst,
				dport)

	if 'regex' in configopts['inspectionmodes']:
		for regex in regexes:
			matchstats['match'] = regex.search(data)
			if matchstats['match']:
				matchstats['detectiontype'] = 'regex'
				matchstats['regex'] = regex
				matchstats['start'] = matchstats['match'].start()
				matchstats['end'] = matchstats['match'].end()
				matchstats['matchsize'] = matchstats['end'] - matchstats['start']
				if configopts['verbose']:
					print '[DEBUG] inspect - [%s#%08d] %s:%s - %s:%s matches regex: \'%s\'' % (
							proto,
							id,
							src,
							sport,
							dst,
							dport,
							getregexpattern(regex))
				return True
			else:
				if configopts['invertmatch']:
					matchstats['detectiontype'] = 'regex'
					matchstats['regex'] = regex
					matchstats['start'] = 0
					matchstats['end'] = datalen
					matchstats['matchsize'] = matchstats['end'] - matchstats['start']
					return True

			if configopts['verbose']:
				print '[DEBUG] inspect - [%s#%08d] %s:%s - %s:%s did not match regex: \'%s\'' % (
						proto,
						id,
						src,
						sport,
						dst,
						dport,
						getregexpattern(regex))

	if 'dfa' in configopts['inspectionmodes']:
		for dfaobject in dfas:
			matched = False

			retncode = dfaobject.match(data)
			dfaobject.reset_dfa()

			if direction == 'CTS':
				memberid = configopts['ctsdfas'][dfaobject]['memberid']
				dfapattern = configopts['ctsdfas'][dfaobject]['dfapattern']
			if direction == 'STC':
				memberid = configopts[addrkey]['stcdfastats'][dfaobject]['memberid']
				dfapattern = configopts[addrkey]['stcdfastats'][dfaobject]['dfapattern']

			dfaexpression = configopts['dfaexpression']

			if retncode == 1 and not configopts['invertmatch']: matched = True
			elif retncode == 0 and configopts['invertmatch']: matched = True

			if matched:
				partialmatch = True

				matchstats['detectiontype'] = 'dfa'
				matchstats['dfaobj'] = dfaobject
				matchstats['dfapattern'] = dfapattern
				matchstats['dfastatecount'] = dfaobject.nQ
				matchstats['start'] = 0
				matchstats['end'] = datalen
				matchstats['matchsize'] = matchstats['end'] - matchstats['start']

				if direction == 'CTS':
					openflows[addrkey]['ctsmatcheddfastats'].update({
													dfaobject: {
															'dfaobject': dfaobject,
															'dfapattern': dfapattern,
															'memberid': memberid,
															'truthvalue': 'True'
														}
												})
	
				if direction == 'STC':
					openflows[addrkey]['stcmatcheddfastats'].update({
													dfaobject: {
															'dfaobject': dfaobject,
															'dfapattern': dfapattern,
															'memberid': memberid,
															'truthvalue': 'True'
														}
												})

				if configopts['verbose']:
					print '[DEBUG] inspect - [%s#%08d] %s:%s - %s:%s matches %s: \'%s\'' % (
							proto,
							id,
							src,
							sport,
							dst,
							dport,
							memberid,
							dfapattern)

			elif configopts['verbose']:
				finalmatch = False
				print '[DEBUG] inspect - [%s#%08d] %s:%s - %s:%s did not match dfa %s: \'%s\'' % (
						proto,
						id,
						src,
						sport,
						dst,
						dport,
						memberid,
						dfapattern)

		if partialmatch:
			exprdict = {}
			for key in dfas:
				if key in openflows[addrkey]['ctsmatcheddfastats']: exprdict[openflows[addrkey]['ctsmatcheddfastats'][key]['memberid']] = openflows[addrkey]['ctsmatcheddfastats'][key]['truthvalue']
				if key in openflows[addrkey]['stcmatcheddfastats']: exprdict[openflows[addrkey]['stcmatcheddfastats'][key]['memberid']] = openflows[addrkey]['stcmatcheddfastats'][key]['truthvalue']

			exprlist = []
			for token in configopts['dfaexpression'].split(' '):
				exprlist.append(token)

			exprboolean = []
			for token in exprlist:
				if token == 'and': exprboolean.append(token)
				elif token == 'or': exprboolean.append(token)
				elif token in exprdict.keys(): exprboolean.append(exprdict[token])
				else: exprboolean.append('False')

			evalboolean = ' '.join(exprboolean)
			finalmatch = eval(evalboolean)
			if configopts['verbose']:
				print '[DEBUG] inspect - [%s#%08d] %s:%s - %s:%s (\'%s\' ==> \'%s\' ==> \'%s\')' % (
						proto,
						id,
						src,
						sport,
						dst,
						dport,
						dfaexpression,
						evalboolean,
						finalmatch)

			if finalmatch:
				matchstats['dfaexpression'] = configopts['dfaexpression']
				if configopts['graph']: graphdfatransitions('%s-%08d-%s.%s-%s.%s' % (proto, id, src, sport, dst, dport))

		return finalmatch


	if 'shellcode' in configopts['inspectionmodes']:
		emulator = emu.Emulator(1024)
		offset = emulator.shellcode_getpc_test(data)
		if offset < 0: offset = 0
		emulator.prepare(data, offset)
		if not emulator.test() and emulator.emu_profile_output:
			emulator.free()
			matchstats['detectiontype'] = 'shellcode'
			matchstats['shellcodeoffset'] = offset
			matchstats['start'] = 0
			matchstats['end'] = datalen
			matchstats['matchsize'] = matchstats['end'] - matchstats['start']
			if configopts['verbose']:
				print '[DEBUG] inspect - [%s#%08d] %s:%s - %s:%s contains shellcode' % (
						proto,
						id,
						src,
						sport,
						dst,
						dport)
			return True

		elif configopts['verbose']: print '[DEBUG] inspect - [%s#%08d] %s:%s - %s:%s doesnot contain shellcode' % (
							proto,
							id,
							src,
							sport,
							dst,
							dport)

	return False


def graphdfatransitions(filename):
	global configopts

	if configopts['graph']:
		class NullDevice():
			def write(self, s): pass

		graphtitle = 'DFA Transition Graph for: \'%s\'' % (matchstats['dfapattern'])
		extension = 'png'
		graphfilename = '%s.%s' % (filename, extension)
		automata = FA(matchstats['dfaobject'])
		automata.draw_graph(graphtitle, 1, 0)
		stdstdout = sys.stdout
		sys.stdout = NullDevice()
		automata.save_graph(graphfilename)
		sys.stdout = sys.__stdout__	

		if configopts['graphdir'] != '.':
			if not os.path.exists(configopts['graphdir']):
				os.makedirs(configopts['graphdir'])
			else:
				if os.path.exists(os.path.join(configopts['graphdir'], graphfilename)):
					os.remove(os.path.join(configopts['graphdir'], graphfilename))

			shutil.move(graphfilename, configopts['graphdir'])

def handletcp(tcp):
	global configopts, opentcpflows, regexengine, shellcodeengine, dfaengine

	id = 0
	showmatch = False
	addrkey = tcp.addr
	((src, sport), (dst, dport)) = tcp.addr

	if not configopts['linemode']:
		if configopts['tcpdone']:
			if configopts['udpdone']:
				if configopts['verbose']:
					if addrkey in opentcpflows: id = opentcpflows[addrkey]['id']
					print '[DEBUG] handletcp - [TCP#%08d] Done inspecting max packets (%d) and max streams (%d), \
							preparing for exit' % (
							id,
							configopts['maxinsppackets'],
							configopts['maxinspstreams'])
				exitwithstats()
			else:
				if configopts['verbose']:
					if addrkey in opentcpflows: id = opentcpflows[addrkey]['id']
					print '[DEBUG] handletcp - [TCP#%08d] Ignoring stream %s:%s - %s:%s (insptcppacketct: %d == maxinspstreams: %d)' % (
							id,
							src,
							sport,
							dst,
							dport,
							configopts['insptcppacketct'],
							configopts['maxinspstreams'])
			return

	regexes = []
	dfas = []
	timestamp = datetime.datetime.fromtimestamp(nids.get_pkt_ts()).strftime('%H:%M:%S | %Y/%m/%d')
	endstates = [ nids.NIDS_CLOSE, nids.NIDS_TIMED_OUT, nids.NIDS_RESET ]

	inspectcts = False
	inspectstc = False
	if len(configopts['ctsregexes']) > 0 or len(configopts['ctsdfas']) > 0: inspectcts = True
	if len(configopts['stcregexes']) > 0 or len(configopts['stcdfas']) > 0: inspectstc = True

	if tcp.nids_state == nids.NIDS_JUST_EST:
		if addrkey not in opentcpflows:
			configopts['streamct'] += 1

			opentcpflows.update({addrkey:{
											'id':configopts['streamct'],
											'totdatasize':0,
											'insppackets':0,
											'ctspacketlendict':{},
											'stcpacketlendict':{},
											'ctsmatcheddfastats':{},
											'stcmatcheddfastats':{}
										}
								})

			if configopts['verbose']:
				print '[DEBUG] handletcp - [TCP#%08d] %s:%s - %s:%s [SYN] (TRACKED: %d)' % (
						opentcpflows[addrkey]['id'],
						src,
						sport,
						dst,
						dport,
						len(opentcpflows))

		if configopts['linemode'] or 'shellcode' in configopts['inspectionmodes']:
			tcp.server.collect = 1
			tcp.client.collect = 1
			if configopts['verbose']:
				print '[DEBUG] handletcp - [TCP#%08d] Enabled both CTS and STC data collection for %s:%s - %s:%s' % (
						opentcpflows[addrkey]['id'],
						src,
						sport,
						dst,
						dport)
		else:
			if inspectcts or 'shellcode' in configopts['inspectionmodes']:
				tcp.server.collect = 1
				if configopts['verbose']:
					print '[DEBUG] handletcp - [TCP#%08d] Enabled CTS data collection for %s:%s - %s:%s' % (
						opentcpflows[addrkey]['id'],
						src,
						sport,
						dst,
						dport)
			if inspectstc or 'shellcode' in configopts['inspectionmodes']:
				tcp.client.collect = 1
				if configopts['verbose']:
					print '[DEBUG] handletcp - [TCP#%08d] Enabled STC data collection for %s:%s - %s:%s' % (
						opentcpflows[addrkey]['id'],
						src,
						sport,
						dst,
						dport)

	if tcp.nids_state == nids.NIDS_DATA:
		tcp.discard(0)

		if tcp.server.count_new > 0:
			direction = 'CTS'
			directionflag = '>'
			count = tcp.server.count
			newcount = tcp.server.count_new
			start = tcp.server.count - tcp.server.count_new
			end = tcp.server.count
			data = tcp.server.data[:tcp.server.count]
			opentcpflows[addrkey]['totdatasize'] += tcp.server.count_new

			if regexengine and 'regex' in configopts['inspectionmodes']:
				for regex in configopts['ctsregexes']:
					regexes.append(regex)

			if dfaengine and 'dfa' in configopts['inspectionmodes']:
				for dfaobj in configopts['ctsdfas'].keys():
					dfas.append(dfaobj)

		if tcp.client.count_new > 0:
			direction = 'STC'
			directionflag = '<'
			count = tcp.client.count
			newcount = tcp.client.count_new
			start = tcp.client.count - tcp.client.count_new
			end = tcp.client.count
			data = tcp.client.data[:tcp.client.count]
			opentcpflows[addrkey]['totdatasize'] += tcp.client.count_new

			if regexengine and 'regex' in configopts['inspectionmodes']:
				for regex in configopts['stcregexes']:
					regexes.append(regex)

		if configopts['verbose']:
			print '[DEBUG] handletcp - [TCP#%08d] %s:%s %s %s:%s [%dB] (CTS: %d | STC: %d | TOT: %d)' % (
					opentcpflows[addrkey]['id'],
					src,
					sport,
					directionflag,
					dst,
					dport,
					newcount,
					tcp.server.count,
					tcp.client.count,
					opentcpflows[addrkey]['totdatasize'])

		configopts['insptcppacketct'] += 1
		configopts['insptcpstreamct'] = opentcpflows[addrkey]['id']

		if configopts['linemode']:
			matchstats['addr'] = addrkey
			matchstats['start'] = start
			matchstats['end'] = end
			matchstats['matchsize'] = matchstats['end'] - matchstats['start']
			matchstats['direction'] = direction
			matchstats['directionflag'] = directionflag
			if configopts['verbose']: print '[DEBUG] handletcp - [TCP#%08d] Skipping inspection as linemode is enabled.' % (
												opentcpflows[addrkey]['id'])
			showtcpmatches(data[matchstats['start']:matchstats['end']])
			return

		if configopts['maxinspstreams'] != 0 and configopts['insptcppacketct'] >= configopts['maxinspstreams']:
			configopts['tcpdone'] = True

		if configopts['offset'] > 0 and configopts['offset'] < count:
			offset = configopts['offset']
		else:
			offset = 0

		if configopts['depth'] > 0 and configopts['depth'] <= (count - offset):
			depth = configopts['depth'] + offset
		else:
			depth = count

		inspdata = data[offset:depth]
		inspdatalen = len(inspdata)

		if configopts['verbose']:
			print '[DEBUG] handletcp - [TCP#%08d] Initiating inspection on %s[%d:%d] - %dB' % (
					opentcpflows[addrkey]['id'],
					direction,
					offset,
					depth,
					inspdatalen)

		matched = inspect('TCP', inspdata, inspdatalen, regexes, dfas, addrkey, direction)

		opentcpflows[addrkey]['insppackets'] += 1
		if direction == 'CTS':
			opentcpflows[addrkey]['ctspacketlendict'].update({ opentcpflows[addrkey]['insppackets']:inspdatalen })
		else:
			opentcpflows[addrkey]['stcpacketlendict'].update({ opentcpflows[addrkey]['insppackets']:inspdatalen })

		if matched:
			if configopts['killtcp']: tcp.kill

			if direction == 'CTS':
				matchstats['direction'] = 'CTS'
				matchstats['directionflag'] = '>'
			elif direction == 'STC':
				matchstats['direction'] = 'STC'
				matchstats['directionflag'] = '<'

			if configopts['streammatches'] == 0:
				configopts['shortestmatch']['stream'] = matchstats['matchsize']
				configopts['shortestmatch']['streamid'] = opentcpflows[addrkey]['id']
				configopts['longestmatch']['stream'] = matchstats['matchsize']
				configopts['longestmatch']['streamid'] = opentcpflows[addrkey]['id']
			else:
				if matchstats['matchsize'] <= configopts['shortestmatch']['stream']:
					configopts['shortestmatch']['stream'] = matchstats['matchsize']
					configopts['shortestmatch']['streamid'] = opentcpflows[addrkey]['id']

				if matchstats['matchsize'] >= configopts['longestmatch']['stream']:
					configopts['longestmatch']['stream'] = matchstats['matchsize']
					configopts['longestmatch']['streamid'] = opentcpflows[addrkey]['id']

			tcp.server.collect = 0
			tcp.client.collect = 0
			configopts['streammatches'] += 1

			matchstats['addr'] = addrkey
			showtcpmatches(data[matchstats['start']:matchstats['end']])
			del opentcpflows[addrkey]
		else:
			opentcpflows[addrkey]['previnspbufsize'] = inspdatalen

	if tcp.nids_state in endstates:
		if addrkey in opentcpflows:
			id = opentcpflows[addrkey]['id']
			del opentcpflows[addrkey]
			if configopts['verbose']:
				if tcp.nids_state == nids.NIDS_CLOSE: state = 'FIN'
				elif tcp.nids_state == nids.NIDS_TIMED_OUT: state = 'TIMED_OUT'
				elif tcp.nids_state == nids.NIDS_RESET: state = 'RST'
				else: state = 'UNKNOWN'
				print '[DEBUG] handletcp - [TCP#%08d] %s:%s - %s:%s [%s] (TRACKED: %d)' % (
						id,
						src,
						sport,
						dst,
						dport,
						state,
						len(opentcpflows))


def showtcpmatches(data):
	global configopts, opentcpflows, matchstats

	proto = 'TCP'
	((src, sport), (dst, dport)) = matchstats['addr']

	if configopts['maxdispbytes'] > 0: maxdispbytes = configopts['maxdispbytes']
	else: maxdispbytes = len(data)

	filename = '%s/%s-%08d.%s.%s.%s.%s' % (configopts['logdir'], proto, opentcpflows[matchstats['addr']]['id'], src, sport, dst, dport)

	if configopts['writelogs']:
		writetofile(proto, opentcpflows[matchstats['addr']]['id'], src, sport, dst, dport, data)

		if configopts['verbose']:
			print '[DEBUG] showtcpmatches - [TCP#%08d] Wrote %dB to %s' % (
					opentcpflows[matchstats['addr']]['id'],
					matchstats['matchsize'],
					filename)

	if 'quite' in configopts['outmodes']:
		if configopts['verbose'] and matchstats['detectiontype'] == 'regex':
			print '[DEBUG] showtcpmatches - [TCP#%08d] %s:%s %s %s:%s matches \'%s\' @ [%d:%d] - %dB' % (
					opentcpflows[matchstats['addr']]['id'],
					src,
					sport,
					matchstats['directionflag'],
					dst,
					dport,
					getregexpattern(matchstats['regex']),
					matchstats['start'],
					matchstats['end'],
					matchstats['matchsize'])
		return

	if configopts['maxdispstreams'] != 0 and configopts['dispstreamct'] >= configopts['maxdispstreams']:
		if configopts['verbose']:
			print '[DEBUG] showtcpmatches - Skipping outmode parsing (dispstreamct: %d == maxdispstreams: %d)' % (
					configopts['dispstreamct'],
					configopts['maxdispstreams'])
		return

	if 'meta' in configopts['outmodes']:
		if matchstats['direction'] == 'CTS': packetlendict = opentcpflows[matchstats['addr']]['ctspacketlendict']
		else: packetlendict = opentcpflows[matchstats['addr']]['stcpacketlendict']
			
		startpacket = 0
		endpacket = 0
		for (pktid, pktlen) in packetlendict.items():
			if startpacket == 0 and matchstats['start'] <= pktlen:
				startpacket = pktid
			endpacket = pktid

		if matchstats['detectiontype'] == 'regex':
			metastr = 'matches regex: \'%s\'' % (getregexpattern(matchstats['regex']))
			packetstats = '| packet[%d] - packet[%d]' % (startpacket, endpacket)
		elif matchstats['detectiontype'] == 'dfa':
			metastr = 'matches dfapattern: \'%s\' (State Count: %d)' % (matchstats['dfaexpression'], matchstats['dfastatecount'])
			packetstats = '| packet[%d] - packet[%d]' % (startpacket, endpacket)
		elif matchstats['detectiontype'] == 'shellcode':
			metastr = 'contains shellcode (Offset: %d)' % (matchstats['shellcodeoffset'])
			packetstats = '| packet[%d] - packet[%d]' % (startpacket, endpacket)
		else:
			metastr = ''
			packetstats = ''

		print '[MATCH] (%08d/%08d) [TCP#%08d] %s:%s %s %s:%s %s' % (
				configopts['insptcppacketct'],
				configopts['streammatches'],
				opentcpflows[matchstats['addr']]['id'],
				src,
				sport,
				matchstats['directionflag'],
				dst,
				dport,
				metastr)

		print '[MATCH] (%08d/%08d) [TCP#%08d] match @ %s[%d:%d] - %dB %s' % (
				configopts['insptcppacketct'],
				configopts['streammatches'],
				opentcpflows[matchstats['addr']]['id'],
				matchstats['direction'],
				matchstats['start'],
				matchstats['end'],
				matchstats['matchsize'],
				packetstats)

	if 'print' in configopts['outmodes']: printable(data[:maxdispbytes])
	if 'raw' in configopts['outmodes']: print data[:maxdispbytes]
	if 'hex' in configopts['outmodes']: hexdump(data[:maxdispbytes])

	configopts['dispstreamct'] += 1


def validatedfaexpr(expr):
	if not re.search(r'm[0-9][1-9]\s*=\s*', expr):
		print '[-] Incorrect DFA expression: \'%s\'' % (expr)
		print '[-] DFA format: \'m[0-9][1-9]\s*=\s*<expr>\''
		print
		sys.exit(1)

	(memberid, dfa) =  expr.split('=', 1)
	return (memberid.strip(), dfa.strip())


def writetofile(proto, id, src, sport, dst, dport, data):
	global configopts, opentcpflows

	try:
		if not os.path.isdir(configopts['logdir']): os.makedirs(configopts['logdir'])
	except OSError, oserr: print '[-] %s' % oserr

	filename = '%s/%s-%08d-%s.%s-%s.%s' % (configopts['logdir'], proto, id, src, sport, dst, dport)

	try:
		if configopts['linemode']: file = open(filename, 'ab+')
		else: file = open(filename, 'wb+')
		file.write(data)
	except IOError, io: print '[-] %s' % io


def exitwithstats():
	global configopts, openudpflows, opentcpflows

	if configopts['verbose'] and (len(opentcpflows) > 0 or len(openudpflows) > 0):
		dumpopenstreams()

	print
	if configopts['packetct'] >= 0:
		print '[U] Processed: %d | Matches: %d | Shortest: %dB (#%d) | Longest: %dB (#%d)' % (
				configopts['inspudppacketct'],
				configopts['packetmatches'],
				configopts['shortestmatch']['packet'],
				configopts['shortestmatch']['packetid'],
				configopts['longestmatch']['packet'],
				configopts['longestmatch']['packetid'])

	if configopts['streamct'] >= 0:
		print '[T] Processed: %d | Matches: %d | Shortest: %dB (#%d) | Longest: %dB (#%d)' % (
				configopts['insptcpstreamct'],
				configopts['streammatches'],
				configopts['shortestmatch']['stream'],
				configopts['shortestmatch']['streamid'],
				configopts['longestmatch']['stream'],
				configopts['longestmatch']['streamid'])

	print '[+] Flowsrch session complete. Exiting.'

	if configopts['packetmatches'] > 0 or configopts['streammatches'] > 0: sys.exit(0)
	else: sys.exit(1)


def dumpopenstreams():
	global openudpflows, opentcpflows

	if len(openudpflows) > 0:
		print
		print '[DEBUG] Dumping open/tracked UDP streams: %d' % (len(openudpflows))

		for (key, value) in openudpflows.items():
			id = value['id']
			keydst = value['keydst']
			matches = value['matches']
			ctsdatasize = value['ctsdatasize']
			stcdatasize = value['stcdatasize']
			totdatasize = value['totdatasize']
			print '[DEBUG] [%08d] %s - %s [matches: %d] (CTS: %dB | STC: %dB | TOT: %dB)' % (
					id,
					key,
					keydst,
					matches,
					ctsdatasize,
					stcdatasize,
					totdatasize)

	if len(opentcpflows) > 0:
		print
		print '[DEBUG] Dumping open/tracked TCP streams: %d' % (len(opentcpflows))

		for (key, value) in opentcpflows.items():
			((src, sport), (dst, dport)) = key
			id = value['id']
			datasize = value['totdatasize']
			print '[DEBUG] [%08d] %s:%s - %s:%s [%dB]' % (id, src, sport, dst, dport, datasize)

	print


def handleip(pkt):
	timestamp = nids.get_pkt_ts()


def dumpargsstats(configopts):
	global regexengine, shellcodeengine, dfaengine

	print '%-30s' % '[DEBUG] Input pcap:', ; print '[ \'%s\' ]' % (configopts['pcap'])
	print '%-30s' % '[DEBUG] Listening device:', ;print '[ \'%s\' ]' % (configopts['device']),
	if configopts['killtcp']:
		print '[ w/ \'killtcp\' ]'
	else:
		print

	print '%-30s' % '[DEBUG] Inspection Modes:', ;print '[',
	for mode in configopts['inspectionmodes']:
		if mode == 'regex': print '\'regex (%s)\'' % (regexengine),
		if mode == 'dfa': print '\'dfa (%s)\'' % (dfaengine),
		if mode == 'shellcode': print '\'shellcode (%s)\'' % (shellcodeengine),
	print ']'

	print '%-30s' % '[DEBUG] CTS regex:', ; print '[',
	for c in configopts['ctsregexes']:
		print '\'%s\'' % getregexpattern(c),
	print '| %d ]' % (len(configopts['ctsregexes']))

	print '%-30s' % '[DEBUG] STC regex:', ; print '[',
	for s in configopts['stcregexes']:
		print '\'%s\'' % getregexpattern(s),
	print '| %d ]' % (len(configopts['stcregexes']))

	print '%-30s' % '[DEBUG] RE stats:', ; print '[ Flags: %d - (' % (configopts['reflags']),
	if configopts['igncase']: print 'ignorecase',
	if configopts['multiline']: print 'multiline',
	print ') ]'

	print '%-30s' % '[DEBUG] DFA expression:',
	print '[ \'%s\' ]' % (configopts['dfaexpression'])

	print '%-30s' % '[DEBUG] Inspection limits:',
	print '[ Streams: %d | Packets: %d | Offset: %d | Depth: %d ]' % (
			configopts['maxinspstreams'],
			configopts['maxinsppackets'],
			configopts['offset'],
			configopts['depth'])

	print '%-30s' % '[DEBUG] Display limits:',
	print '[ Streams: %d | Packets: %d | Bytes: %d ]' % (
			configopts['maxdispstreams'],
			configopts['maxdisppackets'],
			configopts['maxdispbytes'])

	print '%-30s' % '[DEBUG] Output modes:', ; print '[',
	if 'quite' in configopts['outmodes']:
		print '\'quite\'',
		if configopts['writelogs']:
			print '\'write: %s\'' % (configopts['logdir']),
	else:
		if 'meta' in configopts['outmodes']: print '\'meta\'',
		if 'hex' in configopts['outmodes']: print '\'hex\'',
		if 'print' in configopts['outmodes']: print '\'print\'',
		if 'raw' in configopts['outmodes']: print '\'raw\'',
		if 'graph' in configopts['outmodes']: print '\'graph\'',
		if configopts['writelogs']: print '\'write: %s\'' % (configopts['logdir']),
	print ']'

	print '%-30s' % '[DEBUG] Misc options:',
	print '[ BPF: \'%s\' | invertmatch: %s | killtcp: %s | graph: %s | verbose: %s | linemode: %s ]' % (
			configopts['bpf'],
			configopts['invertmatch'],
			configopts['killtcp'],
			configopts['graph'],
			configopts['verbose'],
			configopts['linemode'])
	print


def main():
	global configopts, regexengine, shellcodeengine, dfaengine

	banner = '''\
	    ______              _                            __ 
	   / __/ /___ _      __(_)___  _________  ___  _____/ /_
	  / /_/ / __ \ | /| / / / __ \/ ___/ __ \/ _ \/ ___/ __/
	 / __/ / /_/ / |/ |/ / / / / (__  ) /_/ /  __/ /__/ /_  
	/_/ /_/\____/|__/|__/_/_/ /_/____/ .___/\___/\___/\__/  
	                                /_/                     
	'''
	print '%s' % (banner)

	print '%s v%s - %s' % (configopts['name'], configopts['version'], configopts['desc'])
	print '%s' % configopts['author']
	print

	parser = argparse.ArgumentParser()

	inputgroup = parser.add_mutually_exclusive_group(required=True)
	inputgroup.add_argument(
									'-p',
									metavar='--pcap',
									dest='pcap',
									default='',
									action='store',
									help='input pcap file')
	inputgroup.add_argument(
									'-d',
									metavar='--device',
									dest='device',
									default='lo',
									action='store',
									help='listening device')

	regex_direction_flags = parser.add_argument_group('RegEx per Direction')
	regex_direction_flags.add_argument(
									'-c',
									metavar='--cregex',
									dest='cres',
									default=[],
									action='append',
									required=False,
									help='regex to match against client stream')
	regex_direction_flags.add_argument(
									'-s',
									metavar='--sregex',
									dest='sres',
									default=[],
									action='append',
									required=False,
									help='regex to match against server stream')
	regex_direction_flags.add_argument(
									'-a',
									metavar='--aregex',
									dest='ares',
									default=[],
									action='append',
									required=False,
									help='regex to match against any stream')


	dfa_direction_flags = parser.add_argument_group('DFA per Direction (\'m[0-9][1-9]=<dfa>\')')
	dfa_direction_flags.add_argument(
									'-C',
									metavar='--cdfa',
									dest='cdfas',
									default=[],
									action='append',
									required=False,
									help='DFA expression to match against client stream')
	dfa_direction_flags.add_argument(
									'-S',
									metavar='--sdfa',
									dest='sdfas',
									default=[],
									action='append',
									required=False,
									help='DFA expression to match against server stream')
	dfa_direction_flags.add_argument(
									'-A',
									metavar='--adfa',
									dest='adfas',
									default=[],
									action='append',
									required=False,
									help='DFA expression to match against any stream')
	parser.add_argument(
									'-X',
									metavar='--dfaexpr',
									dest='dfaexpr',
									default=None,
									action='store',
									required=False,
									help='expression to test chain members')

	regex_flags = parser.add_argument_group('RegEx Flags')
	regex_flags.add_argument(
									'-i',
									dest='igncase',
									default=False,
									action='store_true',
									required=False,
									help='ignore case')
	regex_flags.add_argument(
									'-m',
									dest='multiline',
									default=True,
									action='store_false',
									required=False,
									help='disable multiline match')

	content_modifiers = parser.add_argument_group('Content Modifiers')
	content_modifiers.add_argument(
									'-O',
									metavar='--offset',
									dest='offset',
									default=0,
									action='store',
									required=False,
									help='bytes to skip before matching')
	content_modifiers.add_argument(
									'-D',
									metavar='--depth',
									dest='depth',
									default=0,
									action='store',
									required=False,
									help='bytes to look at while matching (starting from offset)')

	inspection_limits = parser.add_argument_group('Inspection Limits')
	inspection_limits.add_argument(
									'-T',
									metavar='--maxinspstreams',
									dest='maxinspstreams',
									default=0,
									action='store',
									type=int,
									required=False,
									help='max streams to inspect')
	inspection_limits.add_argument(
									'-U',
									metavar='--maxinsppackets',
									dest='maxinsppackets',
									default=0,
									action='store',
									type=int,
									required=False,
									help='max packets to inspect')

	display_limits = parser.add_argument_group('Display Limits')
	display_limits.add_argument(
									'-t',
									metavar='--maxdispstreams',
									dest='maxdispstreams',
									default=0,
									action='store',
									type=int,
									required=False,
									help='max streams to display')
	display_limits.add_argument(
									'-u',
									metavar='--maxdisppackets',
									dest='maxdisppackets',
									default=0,
									action='store',
									type=int,
									required=False,
									help='max packets to display')
	display_limits.add_argument(
									'-b',
									metavar='--maxdispbytes',
									dest='maxdispbytes',
									default=0,
									action='store',
									type=int,
									required=False,
									help='max bytes to display')

	output_options = parser.add_argument_group('Output Options')
	output_options.add_argument(
									'-w',
									metavar='logdir',
									dest='writebytes',
									default='',
									action='store',
									required=False,
									nargs='?',
									help='write matching packets/streams')
	output_options.add_argument(
									'-o',
									dest='outmodes',
									choices=('quite', 'meta', 'hex', 'print', 'raw'),
									action='append',
									default=[],
									required=False,
									help='match output mode')

	misc_options = parser.add_argument_group('Misc. Options')
	misc_options.add_argument(
									'-f',
									metavar='--bpf',
									dest='bpf',
									default='',
									action='store',
									required=False,
									help='BPF expression')
	misc_options.add_argument(
									'-g',
									metavar='graphdir',
									dest='graph',
									default='',
									action='store',
									required=False,
									nargs='?',
									help='generate DFA transitions graph')
	misc_options.add_argument(
									'-E',
									dest='shellcode',
									default=False,
									action='store_true',
									required=False,
									help='enable shellcode detection')
	misc_options.add_argument(
									'-v',
									dest='invmatch',
									default=False,
									action='store_true',
									required=False,
									help='invert match')
	misc_options.add_argument(
									'-k',
									dest='killtcp',
									default=False,
									action='store_true',
									required=False,
									help='kill matching TCP stream')
	misc_options.add_argument(
									'-V',
									dest='verbose',
									default=False,
									action='store_true',
									required=False,
									help='verbose output')
	misc_options.add_argument(
									'-L',
									dest='linemode',
									default=False,
									action='store_true',
									required=False,
									help='enable linemode (disables inspection)')

	args = parser.parse_args()

	if args.pcap:
		configopts['pcap'] = args.pcap
		nids.param('filename', configopts['pcap'])
		configopts['livemode'] = False
	elif args.device:
		configopts['device'] = args.device
		nids.param('device', configopts['device'])
		configopts['livemode'] = True

	if args.igncase:
		configopts['igncase'] = True
		configopts['reflags'] |= re.IGNORECASE

	if args.invmatch:
		configopts['invertmatch'] = True

	if args.multiline:
		configopts['multiline'] = True
		configopts['reflags'] |= re.MULTILINE
		configopts['reflags'] |= re.DOTALL

	if regexengine:
		if args.cres:
			if 'regex' not in configopts['inspectionmodes']: configopts['inspectionmodes'].append('regex')
			for c in args.cres:
				configopts['ctsregexes'].append(re.compile(c, configopts['reflags']))

		if args.sres:
			if 'regex' not in configopts['inspectionmodes']: configopts['inspectionmodes'].append('regex')
			for s in args.sres:
				configopts['stcregexes'].append(re.compile(s, configopts['reflags']))

		if args.ares:
			if 'regex' not in configopts['inspectionmodes']: configopts['inspectionmodes'].append('regex')
			for a in args.ares:
				configopts['ctsregexes'].append(re.compile(a, configopts['reflags']))
				configopts['stcregexes'].append(re.compile(a, configopts['reflags']))

	if dfaengine:
		if args.cdfas:
			if 'dfa' not in configopts['inspectionmodes']: configopts['inspectionmodes'].append('dfa')
			for c in args.cdfas:
				(memberid, dfa) = validatedfaexpr(c)
				configopts['ctsdfas'][Rexp(dfa)] = {
									'dfapattern':dfa,
									'memberid':memberid,
									'truthvalue':'False'
								}

		if len(configopts['ctsdfas']) > 0 or len(configopts['stcdfas']) > 0:
			if args.dfaexpr:
				configopts['dfaexpression'] = args.dfaexpr.strip().lower()
			else:
				memberids = []
				for dfa in configopts['ctsdfas'].keys():
					memberids.append(configopts['ctsdfas'][dfa]['memberid'])
					memberids.append('and')

				del memberids[-1]
				configopts['dfaexpression'] = ' '.join(memberids)

	if args.offset:
		configopts['offset'] = int(args.offset)

	if args.depth:
		configopts['depth'] = int(args.depth)

	if args.maxinsppackets:
		configopts['maxinsppackets'] = int(args.maxinsppackets)

	if args.maxinspstreams:
		configopts['maxinspstreams'] = int(args.maxinspstreams)

	if args.maxdisppackets:
		configopts['maxdisppackets'] = int(args.maxdisppackets)

	if args.maxdispstreams:
		configopts['maxdispstreams'] = int(args.maxdispstreams)

	if args.maxdispbytes:
		configopts['maxdispbytes'] = int(args.maxdispbytes)

	if args.writebytes != '':
		configopts['writelogs'] = True
		if args.writebytes != None:
			configopts['logdir'] = args.writebytes
		else:
			configopts['logdir'] = '.'

	if not args.outmodes:
		configopts['outmodes'].append('meta')
		configopts['outmodes'].append('hex')
	else:
		if 'quite' in args.outmodes: configopts['outmodes'].append('quite')
		if 'meta' in args.outmodes: configopts['outmodes'].append('meta')
		if 'hex' in args.outmodes: configopts['outmodes'].append('hex')
		if 'print' in args.outmodes: configopts['outmodes'].append('print')
		if 'raw' in args.outmodes: configopts['outmodes'].append('raw')

	if args.graph != '':
		configopts['graph'] = True
		if args.graph != None:
			configopts['graphdir'] = args.graph
		else:
			configopts['graphdir'] = '.'

	if args.shellcode:
		configopts['inspectionmodes'].append('shellcode')

	if args.bpf:
		configopts['bpf'] = args.bpf
		nids.param('pcap_filter', configopts['bpf'])				

	if args.killtcp:
		if configopts['livemode']: configopts['killtcp'] = True

	if args.verbose:
		configopts['verbose'] = True

	if args.linemode:
		configopts['linemode'] = True

	if not configopts['inspectionmodes'] and not configopts['linemode']:
		configopts['linemode'] = True
		if configopts['verbose']:
			print '[DEBUG] Inspection requires one or more regex direction flags or shellcode detection enabled, none found!'
			print '[DEBUG] Fallback - linemode enabled'
			print

	if configopts['verbose']:
		dumpargsstats(configopts)

	try:
		nids.chksum_ctl([('0.0.0.0/0', False)])
		nids.param('scan_num_hosts', 0)

		nids.init()							
		nids.register_ip(handleip)
		nids.register_udp(handleudp)
		nids.register_tcp(handletcp)

		print '[+] Callback handlers registered. Press any key to continue...',
		try: input()
		except: pass

		print '[+] NIDS initialized, waiting for events...' ; print
		try: nids.run()
		except KeyboardInterrupt: exitwithstats()

	except nids.error, nx:
		print
		print '[-] NIDS error: %s' % nx
		print
		sys.exit(1)
#	except Exception, ex:
#		print
#		print '[-] Exception: %s' % ex
#		print
#		sys.exit(1)

	exitwithstats()								

if __name__ == '__main__':
	main()

