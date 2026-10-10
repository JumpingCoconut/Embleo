import sys
import unittest
from pathlib import Path

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'src'))
from prizm_admission import admission_payload, endpoint


class AdmissionTests(unittest.TestCase):
    def test_native_endpoint_format_and_admission_fields(self):
        payload = admission_payload('room','1234567','tcp-token','udp-token',
                                    'localhost',1234,'127.0.0.1',1235)
        self.assertEqual(payload,dict(RoomId='room',SearchId='1234567',
            JwtTcp='tcp-token',JwtUdp='udp-token',Tcp='localhost:1234',Udp='127.0.0.1:1235'))
        host,port = endpoint('::1',1234).rsplit(':',1)
        self.assertEqual((host,int(port)),('::1',1234))

    def test_rejects_search_codes_that_crash_native_lobby_formatting(self):
        for code in ('trial','123456'):
            with self.subTest(code=code),self.assertRaisesRegex(ValueError,'seven'):
                admission_payload('room',code,'tcp-token','udp-token',
                                  'localhost',1234,'localhost',1235)

    def test_rejects_urls_paths_and_invalid_endpoint_configuration(self):
        for host in ('https://localhost','localhost/path','localhost:1234',
                     ' localhost','localhost\n','', '[::1]', '-bad.example'):
            with self.subTest(host=host),self.assertRaises(ValueError):
                endpoint(host,1234)
        for port in (True,0,65536,'1234'):
            with self.subTest(port=port),self.assertRaises(ValueError):
                endpoint('localhost',port)
        with self.assertRaises(ValueError):
            admission_payload('room','1234567','same','same','localhost',1234,'localhost',1235)
