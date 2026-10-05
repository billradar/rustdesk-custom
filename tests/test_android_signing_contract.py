import json
from pathlib import Path
import os
import shutil
import struct
import sys
import tempfile
import unittest
import zipfile
import yaml
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'scripts'))
import platform_package
from patchsets import patch_hash
ABIS={'aarch64':'arm64-v8a','armv7':'armeabi-v7a','x86_64':'x86_64'}


