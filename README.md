# ansible-hosttech

This repository provides an [Ansible](https://github.com/ansible/ansible) module
which allows to create, modify and delete DNS records for zones hosted at the
Swiss provider [Hosttech](https://www.hosttech.ch/) using their
[API](https://ns1.hosttech.eu/public/api?wsdl).

Simply copy the `library` folder into your folder where your playbooks reside.
You can then use the `hosttech_dns` module.


## Requirements

The module requires the [lxml](http://lxml.de/) Python library. You can install
it with `pip install lxml`.

The module should work fine with both Python 2 and 3.


## Usage

Some examples can be found in the `test.yml` playbook. It needs a file `credentials.yml`
which should create two variables, `hosttech_username` and `hosttech_password`.
These are the API access tokens provided to you by Hosttech when you have an
account with them.

The module is similar to the [Route 53 module](http://docs.ansible.com/route53_module.html).
Simple examples should work the same for both modules (except authentication
identifiers, of course).


## Internal: WSDL Support

Please note that the module provides its own WSDL access functionality. I've
decided for writing my own as I couldn't get it working with all Python WSDL
libraries I tried ([OSA](https://bitbucket.org/sboz/osa/wiki/Home) and
[Zeep](http://docs.python-zeep.org/en/master/)). For Zeep, the problem seems
that the `Map` type used by the API isn't supported; also, the API description
seems to confuse it with `Array` (wild guess: that's because in PHP, maps are
arrays).

The WSDL functionality only supports what I needed for the Hosttech APIs
I was experimenting with, i.e. the ones related to DNS zones and records.
