#!/usr/bin/python
# -*- coding: utf-8 -*-
#
# Copyright (c) 2017-2018 Felix Fontein
# GNU General Public License v3.0+ (see COPYING or https://www.gnu.org/licenses/gpl-3.0.txt)

from __future__ import (absolute_import, division, print_function)
__metaclass__ = type

ANSIBLE_METADATA = {
    'metadata_version': '1.1',
    'status': ['preview'],
    'supported_by': 'community'
}

DOCUMENTATION = '''
---
module: hosttech_dns_record_facts

short_description: retrieve entries in Hosttech DNS service

description:
    - "Retrieves DNS records in Hosttech DNS service U(https://ns1.hosttech.eu/public/api?wsdl)."

requirements:
  - "python >= 2.6"
  - lxml

options:
    zone:
        description:
        - The DNS zone to modify.
        required: true
    record:
        description:
        - The full DNS record to retrieve.
        required: true
    type:
        description:
        - The type of DNS record to retrieve.
        required: true
        choices: ['A', 'CNAME', 'MX', 'AAAA', 'TXT', 'PTR', 'SRV', 'SPF', 'NS', 'CAA']
    hosttech_username:
        description:
        - The username for the Hosttech API user.
        required: true
        type: string
    hosttech_password:
        description:
        - The password for the Hosttech API user.
        required: true
        type: string

author:
    - Felix Fontein (@felixfontein)
'''

EXAMPLES = '''
# Retrieve the details for new.foo.com
- hosttech_dns_record_facts:
      zone: foo.com
      record: new.foo.com
      type: A
      hosttech_username: foo
      hosttech_password: bar
  register: rec

# Use hosttech_dns_record module to delete new.foo.com A record using
# the results from the above command
- hosttech_dns_record:
      state: absent
      zone: foo.com
      record: "{{ rec.set.record }}"
      ttl: "{{ rec.set.ttl }}"
      type: "{{ rec.set.type }}"
      value: "{{ rec.set.value }}"
      hosttech_username: foo
      hosttech_password: bar

'''

RETURN = '''
set:
    description: The fetched record. Is empty if record doesn't exist.
    type: complex
    returned: success
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

from ansible.module_utils.basic import AnsibleModule
from ansible.module_utils.hosttech import (
    HAS_LXML_ETREE, WSDLException, HostTechAPIError, HostTechAPIAuthError, HostTechAPI,
)


def run_module():
    module_args = dict(
        zone=dict(type='str', required=True),
        record=dict(type='str', required=True),
        type=dict(choices=['A', 'CNAME', 'MX', 'AAAA', 'TXT', 'PTR', 'SRV', 'SPF', 'NS', 'CAA'], required=True),
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

    # Fetch result
    if records:
        ttls = set([record.ttl for record in records]),
        data = {
            'record': record_in,
            'type': type_in,
            'ttl': min(*list(ttls)),
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


def main():
    run_module()


if __name__ == '__main__':
    main()
