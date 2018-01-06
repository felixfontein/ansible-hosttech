#!/usr/bin/python
# Copyright (c) 2017-2018 Felix Fontein
# GNU General Public License v3.0+ (see COPYING or https://www.gnu.org/licenses/gpl-3.0.txt)

from __future__ import (absolute_import, division, print_function)
__metaclass__ = type

ANSIBLE_METADATA = {
    'metadata_version': '1.1',
    'status': ['stableinterface'],
    'supported_by': 'community'
}

DOCUMENTATION = '''
---
module: hosttech_dns

short_description: add or delete entries in Hosttech DNS service

version_added: "2.x"

description:
    - "Creates and deletes DNS records in Hosttech DNS service U(https://ns1.hosttech.eu/public/api?wsdl)."

options:
    state:
        description:
        - Specifies the state of the resource record.
        required: true
        choices: ['present', 'absent', 'get']
    zone:
        description:
        - The DNS zone to modify
        required: true
    record:
        description:
        - The full DNS record to create or delete
        required: true
    ttl:
        description:
        - The TTL to give the new record
        required: false
        default: 3600 (one hour)
    type:
        description:
        - The type of DNS record to create
        required: true
        choices: ['A', 'CNAME', 'MX', 'AAAA', 'TXT', 'PTR', 'SRV', 'SPF', 'NS', 'CAA']
    value:
        description:
        - The new value when creating a DNS record.  YAML lists or multiple comma-spaced values are allowed for non-alias records.
        - When deleting a record all values for the record must be specified or it will not be deleted.
        required: false
        default: null
    overwrite:
        description:
        - Whether an existing record should be overwritten on create if values do not match
        required: false
        default: null
    hosttech_username:
        description:
        - The username for the Hosttech API user
        required: true
    hosttech_password:
        description:
        - The password for the Hosttech API user
        required: true

author:
    - Felix Fontein (@felixfontein)
'''

EXAMPLES = '''
# Add new.foo.com as an A record with 3 IPs
- hosttech_dns:
      state: present
      zone: foo.com
      record: new.foo.com
      type: A
      ttl: 7200
      value: 1.1.1.1,2.2.2.2,3.3.3.3
      hosttech_username: foo
      hosttech_password: bar

# Update new.foo.com as an A record with a list of 3 IPs
- hosttech_dns:
      state: present
      zone: foo.com
      record: new.foo.com
      type: A
      ttl: 7200
      value:
        - 1.1.1.1
        - 2.2.2.2
        - 3.3.3.3
      hosttech_username: foo
      hosttech_password: bar

# Retrieve the details for new.foo.com
- hosttech_dns:
      state: get
      zone: foo.com
      record: new.foo.com
      type: A
      hosttech_username: foo
      hosttech_password: bar
  register: rec

# Delete new.foo.com A record using the results from the get command
- hosttech_dns:
      state: absent
      zone: foo.com
      record: "{{ rec.set.record }}"
      ttl: "{{ rec.set.ttl }}"
      type: "{{ rec.set.type }}"
      value: "{{ rec.set.value }}"
      hosttech_username: foo
      hosttech_password: bar

# Add an AAAA record.  Note that because there are colons in the value
# that the IPv6 address must be quoted.
- hosttech_dns:
      state: present
      zone: foo.com
      record: localhost.foo.com
      type: AAAA
      ttl: 7200
      value: "::1"
      hosttech_username: foo
      hosttech_password: bar

# Add a TXT record.
- hosttech_dns:
      state: present
      zone: foo.com
      record: localhost.foo.com
      type: TXT
      ttl: 7200
      value: 'bar'
      hosttech_username: foo
      hosttech_password: bar

# Add a CAA record.
- hosttech_dns:
      state: present
      zone: foo.com
      record: foo.com
      type: CAA
      ttl: 3600
      value:
      - "128 issue letsencrypt.org"
      - "128 iodef mailto:webmaster@foo.com"
      hosttech_username: foo
      hosttech_password: bar

# Add an MX record.
- hosttech_dns:
      state: present
      zone: foo.com
      record: foo.com
      type: MX
      ttl: 3600
      value:
      - "10 mail.foo.com"
      hosttech_username: foo
      hosttech_password: bar

'''

RETURN = '''
set:
    description: The fetched record, when I(state) is I(get). Is empty if record doesn't exist.
    returned: on successful get
    type: complex
    contains:
        record:
            description: The record name
            type: string
            sample: sample.example.com
        type:
            description: The DNS record type
            type: string
            sample: A
        ttl:
            description: The TTL
            type: int
            sample: 3600
        value:
            description: The DNS record
            type: list
            sample:
            - 1.2.3.4
            - 1.2.3.5
'''

try:
    import lxml.etree
    HAS_LXML_ETREE=True
except:
    HAS_LXML_ETREE=False

import sys

if sys.version_info.major < 3:
    from urllib2 import urlopen, Request, HTTPError
else:
    from urllib.request import urlopen, Request
    from urllib.error import HTTPError

from ansible.module_utils.basic import AnsibleModule


# ##########################################################################################################
# # WSDL handling ##########################################################################################
# ##########################################################################################################


class WSDLException(Exception):
    pass


class WSDLError(WSDLException):
    def __init__(self, origin, message):
        super(WSDLError, self).__init__('{0}: {1}'.format(origin, message))
        self.error_origin = origin
        self.error_message = message


class WSDLCodingException(WSDLException):
    pass


def _split_text_namespace(node, text):
    i = text.find(':')
    if i < 0:
        return text, None
    ns = node.nsmap.get(text[:i])
    text = text[i + 1:]
    return text, ns


_NAMESPACE_XSI = 'http://www.w3.org/2001/XMLSchema-instance'
_NAMESPACE_XSD = 'http://www.w3.org/2001/XMLSchema'
_NAMESPACE_XML_SOAP = 'http://xml.apache.org/xml-soap'
_NAMESPACE_XML_SOAP_ENCODING = 'http://schemas.xmlsoap.org/soap/encoding/'


def _set_type(node, namespace, type):
    node.set(lxml.etree.QName(_NAMESPACE_XSI, 'type').text, lxml.etree.QName(namespace, type))


def encode_wsdl(node, value):
    if value is None:
        node.set(lxml.etree.QName(_NAMESPACE_XSI, 'nil').text, 'true')
    elif isinstance(value, str):
        _set_type(node, _NAMESPACE_XSD, 'string')
        node.text = value
    elif isinstance(value, int):
        _set_type(node, _NAMESPACE_XSD, 'int')
        node.text = str(value)
    elif isinstance(value, bool):
        _set_type(node, _NAMESPACE_XSD, 'boolean')
        node.text = ('true' if value else 'false')
    elif isinstance(value, dict):
        _set_type(node, _NAMESPACE_XML_SOAP, 'Map')
        for key, val in value.items():
            child = lxml.etree.Element('item')
            ke = lxml.etree.Element('key')
            encode_wsdl(ke, key)
            child.append(ke)
            ve = lxml.etree.Element('value')
            encode_wsdl(ve, val)
            child.append(ve)
            node.append(child)
    elif isinstance(value, list):
        _set_type(node, _NAMESPACE_XML_SOAP_ENCODING, 'Array')
        for elt in value:
            child = lxml.etree.Element('item')
            encode_wsdl(child, elt)
            node.append(child)
    else:
        raise WSDLCodingException('Do not know how to encode {0}!'.format(type(value)))


def decode_wsdl(node):
    nil = node.get(lxml.etree.QName(_NAMESPACE_XSI, 'nil'))
    if nil == 'true':
        return None
    type_with_ns = node.get(lxml.etree.QName(_NAMESPACE_XSI, 'type'))
    if type_with_ns is None:
        raise WSDLCodingException('Element "{0}" has no "xsi:type" tag!'.format(node))
    type, ns = _split_text_namespace(node, type_with_ns)
    if ns is None:
        raise WSDLCodingException('Cannot find namespace for "{0}"!'.format(type_with_ns))
    if ns == _NAMESPACE_XSD:
        if type == 'boolean':
            if node.text == 'true':
                return True
            if node.text == 'false':
                return False
            raise WSDLCodingException('Invalid value for boolean: "{0}"'.format(node.text))
        elif type == 'int':
            return int(node.text)
        elif type == 'string':
            return node.text
        else:
            raise WSDLCodingException('Unknown XSD type "{0}"!'.format(type))
    elif ns == _NAMESPACE_XML_SOAP:
        if type == 'Map':
            result = dict()
            for item in node:
                if item.tag != 'item':
                    raise WSDLCodingException('Invalid child tag "{0}" in map!'.format(item.tag))
                key = item.find('key')
                if key is None:
                    raise WSDLCodingException('Cannot find key for "{0}"!'.format(item))
                key = decode_wsdl(key)
                value = item.find('value')
                if value is None:
                    raise WSDLCodingException('Cannot find value for "{0}"!'.format(item))
                value = decode_wsdl(value)
                result[key] = value
            return result
        else:
            raise WSDLCodingException('Unknown XSD type "{0}"!'.format(type))
    elif ns == _NAMESPACE_XML_SOAP_ENCODING:
        if type == 'Array':
            result = []
            for item in node:
                if item.tag != 'item':
                    raise WSDLCodingException('Invalid child tag "{0}" in map!'.format(item.tag))
                result.append(decode_wsdl(item))
            return result
        else:
            raise WSDLCodingException('Unknown XSD type "{0}"!'.format(type))
    else:
        raise WSDLCodingException('Unknown type namespace "{0}" (with type "{1}")!'.format(ns, type))


class Parser(object):
    def _parse(self, result, node, where):
        for child in node:
            tag = lxml.etree.QName(child.tag)
            if tag.namespace != self._api:
                raise WSDLCodingException('Cannot interpret {0} item of type "{1}"!'.format(where, tag))
            for res in child.iter('return'):
                result[tag.localname] = decode_wsdl(res)

    def __init__(self, api, root):
        self._main_ns = 'http://schemas.xmlsoap.org/soap/envelope/'
        self._api = api
        self._root = root
        for fault in self._root.iter(lxml.etree.QName(self._main_ns, 'Fault').text):
            fault_code = fault.find('faultcode')
            fault_string = fault.find('faultstring')
            origin = 'server'
            if fault_code is not None and fault_code.text:
                code, code_ns = _split_text_namespace(fault, fault_code.text)
                if code_ns == self._main_ns:
                    origin = code.lower()
            if fault_string is not None and fault_string.text:
                raise WSDLError(origin, fault_string.text)
            raise WSDLError(origin, lxml.etree.tostring(fault).decode('utf-8'))
        self._header = dict()
        self._body = dict()
        for header in self._root.iter(lxml.etree.QName(self._main_ns, 'Header').text):
            self._parse(self._header, header, 'header')
        for body in self._root.iter(lxml.etree.QName(self._main_ns, 'Body').text):
            self._parse(self._body, body, 'body')

    def get_header(self, header):
        return self._header[header]

    def get_result(self, body):
        return self._body[body]

    def __str__(self):
        return 'header={0}, body={1}'.format(self._header, self._body)

    def __repr__(self):
        return '''<?xml version='1.0' encoding='utf-8'?>''' + '\n' + lxml.etree.tostring(self._root, pretty_print=True).decode('utf-8')


class Composer(object):
    @staticmethod
    def _create(tag, namespace=None):
        if namespace:
            return lxml.etree.Element(lxml.etree.QName(namespace, tag))
        else:
            return lxml.etree.Element(tag)

    def __str__(self):
        return '''<?xml version='1.0' encoding='utf-8'?>''' + '\n' + lxml.etree.tostring(self._root, pretty_print=True).decode('utf-8')

    def _create_envelope(self, tag):
        return self._create(tag, self._main_ns)

    def __init__(self, api):
        self._main_ns = 'http://schemas.xmlsoap.org/soap/envelope/'
        self._api = api
        # Compose basic document
        self._root = self._create_envelope('Envelope')
        self._header = self._create_envelope('Header')
        self._root.append(self._header)
        self._body = self._create_envelope('Body')
        self._root.append(self._body)

    def add_auth(self, username, password):
        auth = self._create('authenticate')
        user = self._create('UserName')
        user.text = username
        auth.append(user)
        pw = self._create('Password')
        pw.text = password
        auth.append(pw)
        self._header.append(auth)

    def add_simple_command(self, command, **args):
        command = self._create(command, self._api)
        for arg, value in args.items():
            arg = self._create(arg)
            encode_wsdl(arg, value)
            command.append(arg)
        self._body.append(command)

    def execute(self, debug=False):
        payload = b'''<?xml version='1.0' encoding='utf-8'?>''' + b'\n' + lxml.etree.tostring(self._root)
        req = Request(self._api, payload, {'Content-Type': 'application/xml', 'Content-Length': len(payload)})
        req.get_method = lambda: 'POST'
        try:
            f = urlopen(req, timeout=300)  # 5 minute timeout
            result = f.read()
            code = f.getcode()
            f.close()
        except HTTPError as e:
            result = e.read()
            code = e.getcode()
        if debug:
            print('Result: {0}, content: {1}'.format(code, result.decode('utf-8')))
        if code < 200 or code >= 300:
            Parser(self._api, lxml.etree.fromstring(result))
            raise WSDLError('server', 'Error {0} while executing WSDL command:\n{1}'.format(code, result.decode('utf-8')))
        return Parser(self._api, lxml.etree.fromstring(result))


# ##########################################################################################################
# # HostTech API ###########################################################################################
# ##########################################################################################################


def format_ttl(ttl):
    sec = ttl % 60
    ttl //= 60
    min = ttl % 60
    ttl //= 60
    h = ttl
    result = []
    if h:
        result.append('{0}h'.format(h))
    if min:
        result.append('{0}m'.format(min))
    if sec:
        result.append('{0}s'.format(sec))
    return ' '.join(result)


class DNSRecord(object):
    def __init__(self):
        self.id = None
        self.zone = None
        self.type = None
        self.prefix = None
        self.target = None
        self.ttl = 86400  # 24 * 60 * 60
        self.priority = None

    @staticmethod
    def create_from_encoding(source):
        result = DNSRecord()
        result.id = source['id']
        result.zone = source['zone']
        result.type = source['type']
        result.prefix = source.get('prefix')
        result.target = source['target']
        result.ttl = int(source['ttl'])
        result.priority = source.get('priority')
        return result

    def encode(self, include_ids=False):
        result = {
            'type': self.type,
            'prefix': self.prefix,
            'target': self.target,
            'ttl': self.ttl,
            'priority': self.priority,
        }
        if include_ids:
            result['id'] = self.id
            result['zone'] = self.zone
        return result

    def __str__(self):
        data = []
        if self.id:
            data.append('id: {0}'.format(self.id))
        if self.zone:
            data.append('zone: {0}'.format(self.zone))
        data.append('type: {0}'.format(self.type))
        if self.prefix:
            data.append('prefix: "{0}"'.format(self.prefix))
        else:
            data.append('prefix: (none)')
        data.append('target: "{0}"'.format(self.target))
        data.append('ttl: {0}'.format(format_ttl(self.ttl)))
        if self.priority:
            data.append('priority: {0}'.format(self.priority))
        return 'DNSRecord(' + ', '.join(data) + ')'

    def __repr__(self):
        return self.encode(include_ids=True)


class DNSZone(object):
    def __init__(self, name):
        self.id = None
        self.user = None
        self.name = name
        self.email = None
        self.ttl = 10800  # 3 * 60 * 60
        self.nameserver = None
        self.serial = None
        self.serial_last_update = None
        self.refresh = None
        self.retry = None
        self.expire = None
        self.template = None
        self.ns3 = None
        self.records = []

    @staticmethod
    def create_from_encoding(source):
        result = DNSZone(source['name'])
        result.id = source['id']
        result.user = source.get('user')
        result.email = source.get('email')
        result.ttl = int(source['ttl'])
        result.nameserver = source['nameserver']
        result.serial = source['serial']
        result.serial_last_update = source['serialLastUpdate']
        result.refresh = source['refresh']
        result.retry = source['retry']
        result.expire = source['expire']
        result.template = source.get('template')
        result.ns3 = source.get('ns3')
        result.records = [DNSRecord.create_from_encoding(record) for record in source['records']]
        return result

    def encode(self):
        return {
            'id': self.id,
            'user': self.user,
            'name': self.name,
            'email': self.email,
            'ttl': self.ttl,
            'nameserver': self.nameserver,
            'serial': self.serial,
            'serialLastUpdate': self.serial_last_update,
            'refresh': self.refresh,
            'retry': self.retry,
            'expire': self.expire,
            'template': self.template,
            'ns3': self.ns3,
            'records': [record.encode(include_ids=True) for record in self.records],
        }

    def __str__(self):
        data = []
        if self.id:
            data.append('id: {0}'.format(self.id))
        if self.user:
            data.append('user: {0}'.format(self.user))
        data.append('name: {0}'.format(self.name))
        if self.email:
            data.append('email: {0}'.format(self.email))
        data.append('ttl: {0}'.format(format_ttl(self.ttl)))
        if self.nameserver:
            data.append('nameserver: {0}'.format(self.nameserver))
        if self.serial:
            data.append('serial: {0}'.format(self.serial))
        if self.serial_last_update:
            data.append('serialLastUpdate: {0}'.format(self.serial_last_update))
        if self.refresh:
            data.append('refresh: {0}'.format(self.refresh))
        if self.retry:
            data.append('retry: {0}'.format(self.retry))
        if self.expire:
            data.append('expire: {0}'.format(self.expire))
        if self.template:
            data.append('template: {0}'.format(self.template))
        if self.ns3:
            data.append('ns3: {0}'.format(self.ns3))
        for record in self.records:
            data.append('record: {0}'.format(str(record)))
        return 'DNSZone(\n' + ',\n'.join(['  ' + line for line in data]) + '\n)'

    def __repr__(self):
        return self.encode()


class HostTechAPIError(Exception):
    pass


class HostTechAPIAuthError(Exception):
    pass


class HostTechAPI(object):
    def __init__(self, username, password, api='https://ns1.hosttech.eu/public/api', debug=False):
        """
        Create a new HostTech API instance with given username and password.
        """
        self._api = api
        self._username = username
        self._password = password
        self._debug = debug

    def _prepare(self):
        command = Composer(self._api)
        command.add_auth(self._username, self._password)
        return command

    def _announce(self, msg):
        print('==== {0} ===================================================================================='.format(msg))

    def _execute(self, command, result_name, acceptable_types):
        if self._debug:
            print('Request: {0}'.format(command))
        result = command.execute(debug=self._debug)
        if result.get_header('authenticateResponse') is not True:
            raise HostTechAPIAuthError('Error on authentication!')
        res = result.get_result(result_name)
        if isinstance(res, acceptable_types):
            if self._debug:
                print('Extracted result: {0} (type {1})'.format(res, type(res)))
            return res
        if self._debug:
            print('Result: {0}; extracted type {1}'.format(result, type(res)))
        raise HostTechAPIError('Result has unexpected type {0} (expecting {1})!'.format(type(res), acceptable_types))

    def get_number_of_zones(self):
        """
        Returns number of all zones from the currently logged in user.

        @return The number of zones (int)

        <operation name="getNumberOfZones">
          <documentation>Returns number of all zones from the currently logged in user</documentation>
          <input message="tns:getNumberOfZonesIn"/>
          <output message="tns:getNumberOfZonesOut"/>
        </operation>
        <operation name="getNumberOfZones">
          <soap:operation soapAction="https://ns1.hosttech.eu/public/api#getNumberOfZones"/>
          <input>
            <soap:body use="encoded" encodingStyle="http://schemas.xmlsoap.org/soap/encoding/" namespace="https://ns1.hosttech.eu/public/api"/>
          </input>
          <output>
            <soap:body use="encoded" encodingStyle="http://schemas.xmlsoap.org/soap/encoding/" namespace="https://ns1.hosttech.eu/public/api"/>
          </output>
        </operation>
        <message name="getNumberOfZonesIn"/>
        <message name="getNumberOfZonesOut">
          <part name="return" type="xsd:int"/>
        </message>
        """
        if self._debug:
            self._announce('get number of zones')
        command = self._prepare()
        command.add_simple_command('getNumberOfZones')
        try:
            return self._execute(command, 'getNumberOfZonesResponse', int)
        except WSDLError as e:
            # FIXME
            raise

    def get_zone(self, search):
        """
        Search a zone by name or id.

        @param search: The search string, i.e. a zone name or ID (string)
        @return The zone information (DNSZone)

        <operation name="getZone">
          <documentation>Search a zone by name or id</documentation>
          <input message="tns:getZoneIn"/>
          <output message="tns:getZoneOut"/>
        </operation>
        <operation name="getZone">
          <soap:operation soapAction="https://ns1.hosttech.eu/public/api#getZone"/>
          <input>
            <soap:body use="encoded" encodingStyle="http://schemas.xmlsoap.org/soap/encoding/" namespace="https://ns1.hosttech.eu/public/api"/>
          </input>
          <output>
            <soap:body use="encoded" encodingStyle="http://schemas.xmlsoap.org/soap/encoding/" namespace="https://ns1.hosttech.eu/public/api"/>
          </output>
        </operation>
        <message name="getZoneIn">
          <part name="search" type="xsd:string"/>
        </message>
        <message name="getZoneOut">
          <part name="return" type="soap-enc:Array"/>
        </message>
        """
        if self._debug:
            self._announce('get zone')
        command = self._prepare()
        command.add_simple_command('getZone', search=search)
        try:
            return DNSZone.create_from_encoding(self._execute(command, 'getZoneResponse', dict))
        except WSDLError as e:
            if e.error_origin == 'server' and e.error_message == 'zone not found':
                return None
            raise

    def add_record(self, search, record):
        """
        Adds a new record to an existing zone.

        @param zone: The search string, i.e. a zone name or ID (string)
        @param record: The DNS record (DNSRecord)
        @return The created DNS record (DNSRecord)

        <operation name="addRecord">
          <documentation>Adds a new record to an existing zone</documentation>
          <input message="tns:addRecordIn"/>
          <output message="tns:addRecordOut"/>
        </operation>
        <operation name="addRecord">
          <soap:operation soapAction="https://ns1.hosttech.eu/public/api#addRecord"/>
          <input>
            <soap:body use="encoded" encodingStyle="http://schemas.xmlsoap.org/soap/encoding/" namespace="https://ns1.hosttech.eu/public/api"/>
          </input>
          <output>
            <soap:body use="encoded" encodingStyle="http://schemas.xmlsoap.org/soap/encoding/" namespace="https://ns1.hosttech.eu/public/api"/>
          </output>
        </operation>
        <message name="addRecordIn">
          <part name="search" type="xsd:string"/>
          <part name="recorddata" type="soap-enc:Array"/>
        </message>
        <message name="addRecordOut">
          <part name="return" type="soap-enc:Array"/>
        </message>
        """
        if self._debug:
            self._announce('add record')
        command = self._prepare()
        command.add_simple_command('addRecord', search=search, recorddata=record.encode(include_ids=False))
        try:
            return DNSRecord.create_from_encoding(self._execute(command, 'addRecordResponse', dict))
        except WSDLError as e:
            # FIXME
            raise

    def get_record(self, record_id):
        """
        Get data of one specific record.

        @param record_id: The DNS record ID (int)
        @return The DNS record (DNSRecord)

        <operation name="getRecord">
          <documentation>Get data of one specific record</documentation>
          <input message="tns:getRecordIn"/>
          <output message="tns:getRecordOut"/>
        </operation>
        <operation name="getRecord">
          <soap:operation soapAction="https://ns1.hosttech.eu/public/api#getRecord"/>
          <input>
            <soap:body use="encoded" encodingStyle="http://schemas.xmlsoap.org/soap/encoding/" namespace="https://ns1.hosttech.eu/public/api"/>
          </input>
          <output>
            <soap:body use="encoded" encodingStyle="http://schemas.xmlsoap.org/soap/encoding/" namespace="https://ns1.hosttech.eu/public/api"/>
          </output>
        </operation>
        <message name="getRecordIn">
          <part name="recordId" type="xsd:int"/>
        </message>
        <message name="getRecordOut">
          <part name="return" type="soap-enc:Array"/>
        </message>
        """
        if record_id is None:
            raise HostTechAPIError('Need record ID to get record!')
        if self._debug:
            self._announce('get record')
        command = self._prepare()
        command.add_simple_command('getRecord', recordId=record_id)
        try:
            return DNSRecord.create_from_encoding(self._execute(command, 'getRecordResponse', dict))
        except WSDLError as e:
            # FIXME
            raise

    def update_record(self, record):
        """
        Update a record.

        @param record: The DNS record (DNSRecord)
        @return The DNS record (DNSRecord)

        <operation name="updateRecord">
          <documentation>Update a record</documentation>
          <input message="tns:updateRecordIn"/>
          <output message="tns:updateRecordOut"/>
        </operation>
        <operation name="updateRecord">
          <soap:operation soapAction="https://ns1.hosttech.eu/public/api#updateRecord"/>
          <input>
            <soap:body use="encoded" encodingStyle="http://schemas.xmlsoap.org/soap/encoding/" namespace="https://ns1.hosttech.eu/public/api"/>
          </input>
          <output>
            <soap:body use="encoded" encodingStyle="http://schemas.xmlsoap.org/soap/encoding/" namespace="https://ns1.hosttech.eu/public/api"/>
          </output>
        </operation>
        <message name="updateRecordIn">
          <part name="recordId" type="xsd:string"/>
          <part name="recorddata" type="soap-enc:Array"/>
        </message>
        <message name="updateRecordOut">
          <part name="return" type="soap-enc:Array"/>
        </message>
        """
        if record.id is None:
            raise HostTechAPIError('Need record ID to update record!')
        if self._debug:
            self._announce('update record')
        command = self._prepare()
        command.add_simple_command('updateRecord', recordId=record.id, recorddata=record.encode(include_ids=False))
        try:
            return DNSRecord.create_from_encoding(self._execute(command, 'updateRecordResponse', dict))
        except WSDLError as e:
            # FIXME
            raise

    def delete_record(self, record):
        """
        Delete a record.

        @param record: The DNS record (DNSRecord)
        @return True in case of success (boolean)

        <operation name="deleteRecord">
          <documentation>Delete a record</documentation>
          <input message="tns:deleteRecordIn"/>
          <output message="tns:deleteRecordOut"/>
        </operation>
        <operation name="deleteRecord">
          <soap:operation soapAction="https://ns1.hosttech.eu/public/api#deleteRecord"/>
          <input>
            <soap:body use="encoded" encodingStyle="http://schemas.xmlsoap.org/soap/encoding/" namespace="https://ns1.hosttech.eu/public/api"/>
          </input>
          <output>
            <soap:body use="encoded" encodingStyle="http://schemas.xmlsoap.org/soap/encoding/" namespace="https://ns1.hosttech.eu/public/api"/>
          </output>
        </operation>
        <message name="deleteRecordIn">
          <part name="recordId" type="xsd:string"/>
        </message>
        <message name="deleteRecordOut">
          <part name="return" type="xsd:boolean"/>
        </message>
        """
        if record.id is None:
            raise HostTechAPIError('Need record ID to delete record!')
        if self._debug:
            self._announce('delete record')
        command = self._prepare()
        command.add_simple_command('deleteRecord', recordId=record.id)
        try:
            return self._execute(command, 'deleteRecordResponse', bool)
        except WSDLError as e:
            # FIXME
            raise

    def change_ip(self, from_ip, to_ip):
        """
        Replace an ip in all records of a user.

        @param from_ip: IP address to change (string)
        @param to_ip: new IP address to change to (string)
        @return (integer)

        <operation name="changeIp">
          <documentation>Replace an ip in all records of a user</documentation>
          <input message="tns:changeIpIn"/>
          <output message="tns:changeIpOut"/>
        </operation>
        <operation name="changeIp">
          <soap:operation soapAction="https://ns1.hosttech.eu/public/api#changeIp"/>
          <input>
            <soap:body use="encoded" encodingStyle="http://schemas.xmlsoap.org/soap/encoding/" namespace="https://ns1.hosttech.eu/public/api"/>
          </input>
          <output>
            <soap:body use="encoded" encodingStyle="http://schemas.xmlsoap.org/soap/encoding/" namespace="https://ns1.hosttech.eu/public/api"/>
          </output>
        </operation>
        <message name="changeIpIn">
          <part name="currentIp" type="xsd:string"/>
          <part name="newIp" type="xsd:string"/>
        </message>
        <message name="changeIpOut">
          <part name="return" type="xsd:int"/>
        </message>
        """
        if self._debug:
            self._announce('change IP')
        command = self._prepare()
        command.add_simple_command('changeIp', currentIp=from_ip, newIp=to_ip)
        try:
            return self._execute(command, 'changeIpResponse', int)
        except WSDLError as e:
            # FIXME
            raise

    def change_ttl(self, ip, ttl):
        """
        Replace TTL in all records of a user for a specific IP.

        @param ip: IP address (string)
        @param ttl: TTL in seconds (integer)
        @return (integer)

        <operation name="changeTTL">
          <documentation>Replace TTL in all records of a user for a specific IP</documentation>
          <input message="tns:changeTTLIn"/>
          <output message="tns:changeTTLOut"/>
        </operation>
        <operation name="changeTTL">
          <soap:operation soapAction="https://ns1.hosttech.eu/public/api#changeTTL"/>
          <input>
            <soap:body use="encoded" encodingStyle="http://schemas.xmlsoap.org/soap/encoding/" namespace="https://ns1.hosttech.eu/public/api"/>
          </input>
          <output>
            <soap:body use="encoded" encodingStyle="http://schemas.xmlsoap.org/soap/encoding/" namespace="https://ns1.hosttech.eu/public/api"/>
          </output>
        </operation>
        <message name="changeTTLIn">
          <part name="ip" type="xsd:string"/>
          <part name="ttl" type="xsd:string"/>
        </message>
        <message name="changeTTLOut">
          <part name="return" type="xsd:int"/>
        </message>
        """
        if self._debug:
            self._announce('change TTL')
        command = self._prepare()
        command.add_simple_command('changeTTL', ip=ip, ttl=ttl)
        try:
            return self._execute(command, 'changeTTLResponse', int)
        except WSDLError as e:
            # FIXME
            raise


# ##########################################################################################################
# # Ansible module #########################################################################################
# ##########################################################################################################


def run_module():
    module_args = dict(
        state=dict(type='str', choices=['present', 'absent', 'get'], required=True),
        zone=dict(type='str', required=True),
        record=dict(type='str', required=True),
        ttl=dict(required=False, type='int', default=3600),
        type=dict(choices=['A', 'CNAME', 'MX', 'AAAA', 'TXT', 'PTR', 'SRV', 'SPF', 'NS', 'CAA'], required=True),
        value=dict(required=False, type='list', default=[]),
        overwrite=dict(required=False, type='bool'),
        hosttech_username=dict(type='str', required=True),
        hosttech_password=dict(type='str', required=True, no_log=True),
    )
    required_if = [('state', 'present', ['value']), ('state', 'absent', ['value'])]
    module = AnsibleModule(argument_spec=module_args, required_if=required_if, supports_check_mode=True)

    if not HAS_LXML_ETREE:
        module.fail_json(msg='Needs lxml Python module (pip install lxml)')

    # Get zone and record.
    zone_in = module.params.get('zone').lower()
    record_in = module.params.get('record').lower()
    if zone_in[-1:] == '.':
        zone_in = zone_in[:-1]
    if record_in[-1:] == '.':
        record_in = record_in[:-1]

    # Convert record to prefix
    if not record_in.endswith('.' + zone_in) and record_in != zone_in:
        module.fail_json(msg='Record must be in zone')
    if record_in == zone_in:
        prefix = None
    else:
        prefix = record_in[:len(record_in) - len(zone_in) - 1]

    # Create API and get zone information
    api = HostTechAPI(module.params.get('hosttech_username'), module.params.get('hosttech_password'), debug=False)
    try:
        zone = api.get_zone(zone_in)
        if zone is None:
            module.fail_json(msg='Zone not found')
    except HostTechAPIAuthError as e:
        module.fail_json(msg='Cannot authenticate', error=e.message)
    except HostTechAPIError as e:
        module.fail_json(msg='Internal error (API level)', error=e.message)
    except WSDLException as e:
        module.fail_json(msg='Internal error (WSDL level)', error=e.message)

    # Find matching records
    type_in = module.params.get('type')
    records = []
    for record in zone.records:
        if record.prefix == prefix and record.type == type_in:
            records.append(record)

    # Process get
    if module.params.get('state') == 'get':
        if records:
            ttls = {record.ttl for record in records},
            data = {
                'record': record_in,
                'type': type_in,
                'ttl': min(*ttls),
                'value': [record.target for record in records],
            }
            if len(ttls) > 1:
                data['ttls'] = ttls
        else:
            data = {}
        module.exit_json(
            changed=False,
            set=data,
        )

    # Parse records
    values = []
    value_in = module.params.get('value')
    for value in value_in:
        if type_in in {'PTR', 'MX'}:
            priority, value = value.split(' ', 1)
            values.append((int(priority), value))
        else:
            values.append((None, value))

    # Compare records
    ttl_in = module.params.get('ttl')
    mismatch = False
    mismatch_records = []
    for record in records:
        if record.ttl != ttl_in:
            mismatch = True
            mismatch_records.append(record)
            continue
        val = (record.priority, record.target)
        if val in values:
            values.remove(val)
        else:
            mismatch = True
            mismatch_records.append(record)
            continue
    if values:
        mismatch = True

    # Determine what to do
    to_create = []
    to_delete = []
    to_change = []
    if module.params.get('state') == 'present':
        do_create = False
        if records:
            if mismatch:
                # Mismatch: user wants to overwrite?
                if module.params.get('overwrite'):
                    do_create = True
                    to_delete.extend(mismatch_records)
                else:
                    module.fail_json(msg="Record already exists with different value. Set 'overwrite' to replace it")
            else:
                # No mismatch: don't create
                do_create = False
        else:
            do_create = True
        for priority, target in values:
            if to_delete:
                # If there's a record to delete, change it to new record
                record = to_delete.pop()
                to_change.append(record)
            else:
                # Otherwise create new record
                record = DNSRecord()
                to_create.append(record)
            record.prefix = prefix
            record.type = type_in
            record.ttl = ttl_in
            record.priority = priority
            record.target = target
    if module.params.get('state') == 'absent':
        if not mismatch:
            to_delete.extend(records)

    # Is there nothing to change?
    if len(to_create) == 0 and len(to_delete) == 0 and len(to_change) == 0:
        module.exit_json(changed=False)

    # Actually do something
    if not module.check_mode:
        try:
            for record in to_delete:
                api.delete_record(record)
            for record in to_change:
                api.update_record(record)
            for record in to_create:
                api.add_record(zone_in, record)
        except HostTechAPIAuthError as e:
            module.fail_json(msg='Cannot authenticate', error=e.message)
        except HostTechAPIError as e:
            module.fail_json(msg='Internal error (API level)', error=e.message)
        except WSDLException as e:
            module.fail_json(msg='Internal error (WSDL level)', error=e.message)
    module.exit_json(changed=True)


def main():
    run_module()


if __name__ == '__main__':
    main()
