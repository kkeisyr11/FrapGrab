import unittest
from unittest.mock import Mock
from core.audio_capture import conversation_device


class AudioOutputTests(unittest.TestCase):
    def manager(self,primary='Speakers',devices=None):
        devices=devices or [{'index':1,'name':'Speakers'},{'index':9,'name':'Headphones USB'}]
        manager=Mock()
        manager.get_default_wasapi_loopback.return_value=next(d for d in devices if d['name']==primary)
        manager.get_loopback_device_info_generator.return_value=iter(devices)
        return manager

    def test_explicit_chat_output_does_not_require_steelseries(self):
        self.assertEqual(conversation_device(self.manager(),'Headphones USB')['index'],9)

    def test_same_output_is_not_mixed_twice_but_can_be_used_without_system_audio(self):
        with self.assertRaises(LookupError):conversation_device(self.manager(),'Speakers')
        self.assertEqual(conversation_device(self.manager(),'Speakers',exclude_default=False)['index'],1)

    def test_missing_explicit_device_is_reported_instead_of_silently_substituted(self):
        with self.assertRaisesRegex(ValueError,'niedostępne'):conversation_device(self.manager(),'Disconnected USB')

    def test_auto_sonar_remains_compatible_and_generic_auto_does_not_guess(self):
        devices=[{'index':1,'name':'SteelSeries Sonar Gaming'},{'index':2,'name':'SteelSeries Sonar Chat'}]
        self.assertEqual(conversation_device(self.manager(devices[0]['name'],devices))['index'],2)
        with self.assertRaises(LookupError):conversation_device(self.manager())

    def test_default_chat_is_recorded_once_or_alone(self):
        devices=[{'index':1,'name':'SteelSeries Sonar Chat'}]
        with self.assertRaises(LookupError):conversation_device(self.manager(devices[0]['name'],devices))
        self.assertEqual(conversation_device(self.manager(devices[0]['name'],devices),exclude_default=False)['index'],1)


if __name__=='__main__':unittest.main()
