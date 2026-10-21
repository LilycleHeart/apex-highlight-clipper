import os
import unittest
from unittest.mock import patch

import numpy as np

from combat_statistics import final_counter_reader
from engine_pool import clear_pool


class CounterReaderReuseTests(unittest.TestCase):
    def test_exact_pixel_results_survive_endpoint_calls_without_inventing_votes(self):
        class Reader:
            def __init__(self,*args):self.calls=0
            def __call__(self,images):
                self.calls+=1
                return [('123',.99) for _ in images],0.
        image=np.zeros((20,30,3),np.uint8)
        with patch.dict(os.environ,{'APEX_OCR_POOL':'1','APEX_OCR_BACKEND':'cpu'}),patch('numeric_reader.NumericReader',Reader):
            clear_pool();first=final_counter_reader();first([image])
            second=final_counter_reader();self.assertIs(first,second)
            self.assertEqual(second([image])[0],[('123',.99)])
            self.assertEqual(first.recognizer.calls,1);self.assertEqual(first.stats()['exact_reuse'],1)
            changed=image.copy();changed[0,0]=255;second([changed])
            self.assertEqual(first.recognizer.calls,2)
            clear_pool()

    def test_explicit_pool_disable_does_not_reuse_counter_reader(self):
        with patch.dict(os.environ,{'APEX_OCR_POOL':'0'}),patch('numeric_reader.NumericReader',return_value=object()):
            self.assertIsNot(final_counter_reader(),final_counter_reader())


if __name__=='__main__':unittest.main()
