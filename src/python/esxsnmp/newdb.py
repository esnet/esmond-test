"""Implement a RESTish API to ESxSNMP data.


"""

import sys
import time
import os
import web
from web.webapi import HTTPError
import simplejson
import urllib
from fpconst import isNaN
import logging

import tsdb
from tsdb.error import *
import esxsnmp.sql
from esxsnmp.sql import Device, OID, OIDSet, IfRef
from esxsnmp.util import get_logger, remove_metachars
from esxsnmp.error import *

from sqlalchemy.orm.exc import NoResultFound, MultipleResultsFound

import pprint

#
# XXX this whole thing should be refactored to break each individual part of
# the request tree into it's own self contained class and called directly from
# the url pattern matching below.
#
urls = (
        '/snmp/.*', 'SNMPHandler',
        '/bulk/?', 'BulkHandler',
        )


SNMP_URI = '/snmp'

def remove_metachars(name):
    """remove troublesome metacharacters from ifDescr"""
    for (char,repl) in (("/", "_"), (" ", "_")):
        name = name.replace(char, repl)
    return name

def split_url(rest):
    parts = rest.split('/', 1)
    if len(parts) == 1:
        return parts[0], ''
    else:
        return parts[0], parts[1]

def parse_query_string():
    d = {}

    if web.ctx.query:
        kvpairs = web.ctx.query[1:].split('&')
        for kvp in kvpairs:
            k,v = kvp.split('=')
            d[k] = v

    return d

def get_time_range(args):
    begin="'-infinity'"
    end="'infinity'"

    if args.has_key('begin'):
        begin = "TIMESTAMP 'epoch' + %s * INTERVAL '1 second'" % args['begin']
    if args.has_key('end'):
        end = "TIMESTAMP 'epoch' + %s * INTERVAL '1 second'" % args['end']
    if not args.has_key('begin') and not args.has_key('end'):
        begin = end = "'NOW'"

    return begin, end

# XXX this should be reworked, can we do it with metadata alone?  probably
# once TSDB uses SQLite for metadata
device_oidset = {}
def get_traffic_oidset(device_name):
    global DB

    try:
        DB.get_set('/%s/SuperFastPollHC' % (device_name))
        r = ('SuperFastPollHC', 'HC')
    except:
        try:
            DB.get_set('/%s/FastPollHC' % (device_name))
            r = ('FastPollHC', 'HC')
        except:
            r = ('FastPoll', '')

    return r


def encode_device(dev, uri, children=[]):
#    print dev.end_time
    return dict(begin_time=dev.begin_time, end_time=dev.end_time,
            name=dev.name, active=dev.active, children=children, uri=uri)

def encode_ifref(ifref, uri, device, children=[]):
#    print ifref
    return dict(
            begin_time=ifref.begin_time,
            end_time=ifref.end_time,
            ifIndex=ifref.ifindex,
            ifDescr=ifref.ifdescr,
            ifAlias=ifref.ifalias,
            ifSpeed=ifref.ifspeed,
            ifHighSpeed=ifref.ifhighspeed,
            ipAddr=ifref.ipaddr,
            uri=uri,
            device_uri='%s/%s' % (SNMP_URI, device.name))

def make_children(uri_prefix, children):
    return [ dict(name=child, uri="%s/%s" % (uri_prefix, child)) for child in
            children ]

class BulkHandler:
    def __init__(self):
        self.uris = []
        self.snmp_handler = SNMPHandler()

    def GET(self):
        print "ERR> GET not allowed for bulk"
        return web.notfound() # GET not supported

    def POST(self):
        t0 = time.time()
        data = web.input()
        if data.has_key('uris'):
            return self.OLDPOST()

        if data.has_key('calcq'):
            return self.calcq(data['calcq'])

        if not data.has_key('q'):
            print "ERR> No q argument:", ",".join(data.keys())
            return web.webapi.BadRequest()

        #print ">>> Q ", data['q']

        try:
            self.queries = simplejson.loads(data['q'])
        except ValueError, e:
            print "ERR> BAD JSON:", data['q'], str(e)
            return web.webapi.BadRequest()

        r = {}

        for q in self.queries:
            try:
                id, uri = self.uri_from_json(q)
            except BadQuery, e:
                r[id] = dict(result=None, error=str(e))
                continue

            out = self.snmp_handler.GET(uri=uri, raw=True)

            if isinstance(out, HTTPError):
                r[id] = dict(result=None, error=str(out))
            else:
                r[id] = dict(result=out, error=None)

        web.ctx.status = "200 OK"
        print "grabbed %d vars in %f sec" % (len(r), time.time()-t0)

        return simplejson.dumps(r)

    def uri_from_json(self, q):
        try:
            uri = q['uri']
        except KeyError:
            raise BadQuery("query does not contain a uri")

        try:
            id = q['id']
        except KeyError:
            raise BadQuery("query does not contain an id")

        del q['uri']
        del q['id']

        args = ["%s=%s" % (k, v) for k,v in q.iteritems()]

        return id, uri + '?' + '&'.join(args)

    def calcq(self, q):
        try:
            queries = simplejson.loads(q)
        except ValueError, e:
            print "ERR> BAD JSON:", q, str(e)
            return web.webapi.BadRequest()

        i = 0
        results = {}
        for query in queries:
            r = dict(error=None, result=None)

            if not query.has_key('id'):
                query['id'] = 'anon%d' % i
                i += 1

            if not query.has_key('func'):
                r.error = "func not defined"
                results[query['id']] = r
                continue

            if query['func'] not in ['sum']:
                r.error = "unknown function: %s" % query['func']
                results[query['id']] = r
                continue

            calcf = getattr(self, 'calcf_' + query['func'])
    
            if not query.has_key('uris'):
                r.error = "uris not defined"
                results[query['id']] = r
                continue

            if not query.has_key('args'):
                r.error = "args not defined"
                results[query['id']] = r
                continue

            args = [ "%s=%s" % (k,v) for k,v in query['args'].iteritems() ]
            args = "&".join(args)

            data = []
            for uri in query['uris']:
                uri += '?' + args
                d = self.snmp_handler.GET(uri=uri, raw=True)
                print ">>> d = ", str(d)
                if d:
                    data.append(d['data'])

            r['result'] = calcf(data)
            results[query['id']] = r

        return simplejson.dumps(results)

    def calcf_sum(self, data):
        r = []
        for i in range(len(data[0])):
            x = 0
            for j in range(len(data)):
                x += data[j][i][1]
            r.append([data[0][i][0], x])

        return r

    def OLDPOST(self):
        data = web.input()
        if not data.has_key('uris'):
            print "ERR> no uris in POST"
            return web.webapi.BadRequest()

        try:
            self.uris = simplejson.loads(data['uris'])
        except ValueError, e:
            print ">>> BAD JSON:", data['uris'], str(e)
            return web.webapi.BadRequest()

        r = {}

        for uri in self.uris:
            #print ">>> grabbing ", uri
            out = self.snmp_handler.GET(uri=uri, raw=True)
            if isinstance(out, HTTPError):
                r[uri] = dict(result=None, error=str(out))
            else:
                r[uri] = dict(result=out, error=None)

        return simplejson.dumps(r)
        
class SNMPHandler:
    def __init__(self):
        self.db = tsdb.TSDB("/ssd/esxsnmp/data", mode="r")
        self.session = esxsnmp.sql.Session()

        self.log = get_logger("newdb")

    def __del__(self):
        self.session.close()

    def GET(self, uri=None, raw=False, args=None):
        # XXX hack because Apache performs a URL decode on PATH_INFO
        # we need /'s encoded as %2F
        # also apache config option: AllowEncodedSlashes On
        # see http://wsgi.org/wsgi/WSGI_2.0

        if not uri:
            uri = web.ctx.environ['REQUEST_URI']

        try:
            uri, args = uri.split('?')
        except ValueError:
            pass


        if args:
            web.ctx.query = "?" + args

        print ">>> ", uri, web.ctx.query

        parts = uri.split('/')
        device_name = parts[2]
        rest = '/'.join(parts[3:])

        self.log.debug( "QQQ: " + " ". join((str(device_name), str(rest),
            str(web.ctx.query))))

        if not device_name:
            args = parse_query_string()
            if args.has_key('interface_descr'):
                descr_pattern = "%%%s%%" % args['interface_descr']
                r = self.get_interfaces_by_descr(descr_pattern)
            else:
                r =  self.list_devices()
        elif parts[3] == 'interface' and len(parts) > 5 and parts[5]:
            r = self.get_interface_data(device_name, parts[4], parts[5],
                    '/'.join(parts[6:]))
        else:
            try:
                device = self.session.query(Device).filter_by(name=device_name)
                device = device.order_by('end_time').all()[-1]
            except NoResultFound:
                print "ERR> NoResultFound"
                return web.notfound()

            if not rest:
                r = self.get_device(device)
            else:
                next, rest = split_url(rest)
                if next == 'interface':
                    r = self.get_interface_set(device, rest)
                elif next == 'system':
                    r = self.get_system(device, rest)
                else:
                    r = web.notfound()

        if raw or isinstance(r, HTTPError):
            return r
        else:
            return simplejson.dumps(r)


    def list_devices(self, active=True):
        """Returns a JSON array of objests representing device names and URIs.

        Example:

        [ {'name': 'router1', 'uri': 'http://example.com/snmp/router1/' },
          {'name': 'router2', 'uri': 'http://example.com/snmp/router2/' } ]
        
        """

        active='t'

        args = parse_query_string()
        begin, end = get_time_range(args)

        if args.has_key('active'):
            active = bool(args['active'])

        limit = """
            device.end_time > %(begin)s
            AND device.begin_time < %(end)s
            AND active = '%(active)s'""" % locals()

#        print ">>>",limit
        devices = self.session.query(esxsnmp.sql.Device).filter(limit)
        r = [dict(name=d.name, uri="%s/%s" % (SNMP_URI, d.name))
                for d in devices]
        return dict(children=r)

    def get_device(self, device):
        """Returns a JSON object representing a device.

        A device JSON object has the following fields:

            :param name: the name of the device
            :param begin_time: start time in seconds since the epoch
            :param end_time: start time in seconds since the epoch
            :param active: should the device be polled, boolean
            :param subsets: an array of available subsets
            :param uri: URI for this device

        For ``begin_time`` and ``end_time`` the values 0 and 2147483647 have
        special significance.  0 represents -infinity and 2147483647
        represents infinity.  This should be fixed.

        Example:

             { 'name': 'router1',
               'begin_time': 0,
               'end_time': 2147483647,
               'active': true,
               'subsets': ['system', 'interface'],
               'uri': 'http://example.com/snmp/router1/' }

        """

        # XXX once database is rearranged this will be dynamic
        subsets=['interface', 'system']
        r = make_children('%s/%s' % (SNMP_URI, device.name), subsets)
        return encode_device(device, '%s/%s' % (SNMP_URI, device.name),
            children=r)

    def get_interface_set(self, device, rest):
        active='t'

#        print ">>> XXQ", web.ctx.query, rest
        args = parse_query_string()
        begin, end = get_time_range(args)
        deviceid = device.id

        limit = """
            ifref.end_time > %(begin)s
            AND ifref.begin_time < %(end)s
            AND ifref.deviceid = %(deviceid)s""" % locals()

#        print ">>>",limit

        ifaces = self.session.query(IfRef).filter(limit)
        ifset = map(lambda x: x.ifdescr, ifaces)

        if not rest:
            speed = None
            def build_iface(iface):

                if not iface.ifhighspeed or iface.ifhighspeed == 0:
                    speed = iface.ifspeed
                else:
                    speed = iface.ifhighspeed * int(1e6)
                return dict(name=iface.ifdescr,
                    uri="%s/%s/interface/%s/" % (SNMP_URI, device.name,
                        remove_metachars(iface.ifdescr)),
                    descr=iface.ifalias,
                    speed=speed)

            l = map(build_iface, ifaces.all())
            return dict(children=l)
        else:
            next, rest = split_url(rest)
            next = urllib.unquote(next)
#            print ">>>>", next, rest
            return self.get_interface(device, ifaces, next, rest)

    def get_interfaces_by_descr(self, descr_pattern):
        # XXX quick hack to test search idea, totally needs to be written like
        # this whole module.... *sigh*
        args = parse_query_string()
        begin, end = get_time_range(args)

        limit = """
            ifref.end_time > %(begin)s
            AND ifref.begin_time < %(end)s""" % locals()

        ifaces = self.session.query(IfRef).filter(limit)
        ifaces = ifaces.filter(IfRef.ifalias.like(descr_pattern))
        children = ['in', 'out', 'error', 'discard']
        l = []
        for ifref in ifrefs:
            uri = '%s/%s/interface/%s' % (SNMP_URI, device.name,
                    iface.replace('/','_'))
            kids = make_children(uri, children)
            l.append(encode_ifref(ifref, uri, device, children=kids))

        return l

    def get_interface(self, device, ifaces, iface, rest):
        """Returns a JSON object representing an interface.

        An interface JSON object has the following fields:

            :param ifIndex: SNMP ifIndex
            :param ifDescr: SNMP ifDescr, the interface name
            :param ifAlias: SNMP ifAlias, the interface description
            :param ipAddr: SNMP ipAddr, IP address of interface
            :param ifSpeed: SNMP ifSpeed, interface speed in bit/sec
            :param ifHighSpeed: SNMP ifHighSpeed, interface speed in Mbit/sec
            :param begin_time: start time in seconds since the epoch
            :param end_time: start time in seconds since the epoch
            :param subsets: an array of available subsets
            :param uri: URI for this interface
            :param device_uri: URI for the device this interface belongs to

        For ``begin_time`` and ``end_time`` the values 0 and 2147483647 have
        special significance.  0 represents -infinity and 2147483647
        represents infinity.  This should be fixed.

        Example:

             [{ 'ifIndex': 1,
               'ifDescr': 'xe-2/0/0',
               'ifAlias': '10Gig to Timbuktu',
               'ipAddr': '10.255.255.1',
               'ifSpeed': 0,
               'ifHighSpeed': 10000,
               'begin_time': 0,
               'end_time': 2147483647,
               'subsets': ['in', 'out'],
               'uri': 'http://example.com/snmp/router1/interface/xe-2_0_0', }
               'device_uri': 'http://example.com/snmp/router1/' }]
        """

        # XXX fill in ifref info
        children = ['in', 'out', 'error', 'discard']

        iface = iface.replace('_', '/')
        if not rest:
            t0 = time.time()
            ifrefs = ifaces.filter_by(ifdescr=iface)
#            print ifrefs.all()
            l = []
            t1 = time.time()
            print "t>> iface select %f" % (t1 - t0)
            t0 = t1
            for ifref in ifrefs:
                uri = '%s/%s/interface/%s' % (SNMP_URI, device.name,
                        iface.replace('/','_'))
                kids = make_children(uri, children)
                l.append(encode_ifref(ifref, uri, device, children=kids))

            t1 = time.time()
            print "t>> iface process %f" % (t1 - t0)

            if l:
                return l
            else:
                return web.notfound()
        else:
            next, rest = split_url(rest)
            if next in children:
                return self.get_interface_data(device.name, iface, next, rest)
            else:
                return web.notfound()

    def get_interface_data(self, devicename, iface, dataset, rest):
        """Returns a JSON object representing counter data for an interface.

        An interface data JSON object has the following fields:

            :param data: a list of tuples.  each tuple is [timestamp, value]
            :param begin_time: the requested begin_time
            :param end_time: the requested end_time
            :param agg: the requested aggregation period
            :param cf: the requestion consolidation function

        Example:

            {"agg": "30",
             "end_time": 1254350090,
             "data": [[1254349980, 163.0],
                      [1254350010, 28.133333333333333],
                      [1254350040, 96.966666666666669],
                      [1254350070, 110.03333333333333]],
             "cf": "average",
             "begin_time": 1254350000}
        """

        next = None
        if rest:
            next, rest = split_url(rest)
            if next == 'aggs':
                # XXX list actual aggs
                return dict(aggregates=[30], cf=['average'])
            elif dataset not in ['errors', 'discards'] and next not in ['in', 'out']:
                return web.notfound("nope")

        args = parse_query_string()

        if args.has_key('begin'):
            begin = args['begin']
        else:
            begin = int(time.time() - 3600)

        if args.has_key('end'):
            end = args['end']
        else:
            end = int(time.time())

        if args.has_key('cf'):
            cf = args['cf']
        else:
            cf = 'average'

        if args.has_key('oidset'):
            traffic_oidset = args['oidset']
            if traffic_oidset == 'FastPoll':
                traffic_mod = ''
            else:
                traffic_mod = 'HC'
        else:
            traffic_oidset, traffic_mod = get_traffic_oidset(devicename)

        if args.has_key('agg'):
            agg = args['agg']
            suffix = 'TSDBAggregates/%s/' % (args['agg'], )
        else:
            if cf == 'raw':
                suffix = ''
                agg = ''
            else:
                if traffic_oidset != 'SuperFastPollHC':
                    suffix = 'TSDBAggregates/30/'
                    agg = '30'
                else:
                    suffix = 'TSDBAggregates/10/'
                    agg = '10'

        if dataset in ['in', 'out']: # traffic
            begin, end = int(begin), int(end)

            path = '%s/%s/if%s%sOctets/%s/%s' % (devicename, traffic_oidset,
                traffic_mod, dataset.capitalize(),
                remove_metachars(iface), suffix)
        elif dataset in ['errors', 'discards']:
            path = '%s/Errors/if%s%s/%s' % (devicename, next.capitalize(),
                    dataset.capitalize(), remove_metachars(iface))
            path += '/TSDBAggregates/60/'
        else:
            pass

        try:
            v = self.db.get_var(path)
        except TSDBVarDoesNotExistError:
            print "ERR> var doesn't exist: %s" % path
            return web.notfound()  # Requested variable does not exist
        except InvalidMetaData:
            print "ERR> invalid metadata: %s" % path
            return web.notfound()

        data = v.select(begin=begin, end=end)
        data = [d for d in data]
        r = []

        for datum in data:
            if cf != 'raw':
                d = [datum.timestamp, getattr(datum, cf)]
            else:
                d = [datum.timestamp, datum.value]

            if isNaN(d[1]):
                d[1] = None

            r.append(d)

        result = dict(data=r, begin_time=begin, end_time=end, cf=cf, agg=agg)

        if args.has_key('calc'):
            if args.has_key('calc_func'):
                calc_func = args['calc_func']
            else:
                calc_func = 'average'

            r = self.calculate(args['calc'], agg, calc_func, r)
            if isinstance(r, HTTPError):
                return r

            result['data'] = r
            result['calc'] = args['calc']
            result['calc_func'] = calc_func

            # these don't make sense if we're using calc
            del result['agg']
            del result['cf']

        return result
            

    def calculate(self, period, base_period, cf, data):
        points_per_step = int(period)/int(base_period)

        try:
            f = getattr(self, "calculate_%s" % cf)
        except AttributeError:
            print "ERR> unknown calc function: %s" % cf
            return web.webapi.BadRequest() # invalid consolidation function

        r = []
        for i in range(0, len(data), points_per_step):
            r.append(f(data[i:i+points_per_step]))

        return r

    def calculate_average(self, data):
        total = 0
        for d in data:
            if d[1]:
                total += d[1]

        return (data[0][0], total/len(data))

    def calculate_max(self, data):
        max = data[0][1]
        for d in data[1:]:
            if d[1] > max:
                max = d[1]

        return [data[0][0], max]

    def calculate_min(self, data):
        min = data[0][1]
        for d in data[1:]:
            if d[1] < min:
                min = d[1]

        return (data[0][0], min)

    def get_system(self, device, rest):
        pass

class LoggingMiddleware:

    def __init__(self, application):
        self.__application = application

    def __call__(self, environ, start_response):
        errors = environ['wsgi.errors']
        pprint.pprint(('REQUEST', environ), stream=errors)

        def _start_response(status, headers):
            pprint.pprint(('RESPONSE', status, headers), stream=errors)
            return start_response(status, headers)

        return self.__application(environ, _start_response)

def esdb_wsgi():
    esxsnmp.sql.setup_db('postgres://snmp:ed1nCit0@localhost/esxsnmp')
    global DB 
    DB = tsdb.TSDB("/ssd/esxsnmp/data", mode="r")
    application = web.application(urls, globals()).wsgifunc()
    sys.stdout = sys.stderr
    #application = LoggingMiddleware(application)
    #application = web.profiler(application)
    return application

if __name__ == '__main__':
    from esxsnmp.config import get_opt_parser, get_config, get_config_path
    from esxsnmp.error import ConfigError
    """
    argv = sys.argv
    oparse = get_opt_parser(default_config_file=get_config_path())
    (opts, args) = oparse.parse_args(args=argv)

    try:
        config = get_config(opts.config_file, opts)
    except ConfigError, e:
        print e
        sys.exit(1)
    """

    esxsnmp.sql.setup_db('postgres://snmp:ed1nCit0@localhost/esxsnmp')
    application = web.application(urls, globals())
    application.run()

