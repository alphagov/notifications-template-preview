#!/usr/bin/env python
import sys
import yaml
import os
import subprocess
import numpy as np
import re


class ColorMapping():

    RGB_COLOR_DEFINITION = re.compile(
        b'(.* )?([01]\.?[0-9]*) ([01]\.?[0-9]*) ([01]\.?[0-9]*) (RG|rg)(.*)$'
    )

    MAPPING_FILE = os.path.join(
        os.path.dirname(os.path.realpath(__file__)),
        'colors.yaml',
    )

    def __init__(self):
        with open(self.MAPPING_FILE, 'r') as colors_file:
            self.colors = yaml.load(
                ''.join(
                    '!!python/tuple {}\n'.format(line)
                    for line in colors_file.readlines()
                )
            )
        self.replaced_colors = {}

    def __call__(self, line):
        match = re.match(self.RGB_COLOR_DEFINITION, line)
        if match:
            replacement = b''.join((
                match.group(1) or b'',
                self.get_cmyk_color_from_match(match),
                b' k' if match.group(5) == b'rg' else b' K',
                match.group(6),
            ))
            return re.sub(self.RGB_COLOR_DEFINITION, replacement, line)
        else:
            return line

    def output_log(self):
        for old, new in self.replaced_colors.items():
            print('Replaced {} with {}'.format(old, new), file=sys.stderr)

    def get_closest_cmyk_color(self, rgb_tuple):
        closenesses = [
            np.linalg.norm(np.asarray(rgb_key) - np.asarray(rgb_tuple))
            for rgb_key in self.colors.keys()
        ]
        index_of_closest_match = closenesses.index(min(closenesses))
        return list(self.colors.values())[index_of_closest_match]

    def log_replacement(self, rgb_tuple, cmyk_tuple):
        self.replaced_colors[
            'R {}, G {}, B {}'.format(*rgb_tuple)
        ] = 'C {}, M {}, Y {}, K {}'.format(*cmyk_tuple)

    def get_cmyk_color_from_match(self, match):
        rgb_tuple = tuple(float(match.group(i)) for i in (2, 3, 4))
        cmyk_tuple = self.get_closest_cmyk_color(rgb_tuple)
        self.log_replacement(rgb_tuple, cmyk_tuple)
        return '{} {} {} {}'.format(*cmyk_tuple).encode('UTF-8')


class Pdf:
    def __init__(self, input_file, output_file):
        print("Reading {}".format(input_file))
        self.input = subprocess.Popen(
            [
                "pdftk",
                input_file,
                "output",
                "-",
                "uncompress",
            ],
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
        )
        print("Output is {}".format(output_file))
        self.output = subprocess.Popen(
            [
                "gs",
                "-o",
                output_file,
                "-sDEVICE=pdfwrite",
                "-sProcessColorModel=DeviceCMYK",
                "-sColorConversionStrategy=None",
                "-sColorConversionStrategyForImages=CMYK",
                "-sDownsampleMonoImages=false ",
                "-sDownsampleGrayImages=false ",
                "-sDownsampleColorImages=false ",
                "-sAutoFilterColorImages=false ",
                "-sAutoFilterGrayImages=false ",
                "-sColorImageFilter=/FlateEncode ",
                "-sGrayImageFilter=/FlateEncode ",
                "-dAutoRotatePages=/None ",
                "-",
            ],
            stdin=subprocess.PIPE,
        )

    def __enter__(self):
        return self

    def read(self):
        return self.input.stdout.readlines()

    def write(self, line):
        return self.output.stdin.write(line)

    def __exit__(self, exc_type, exc_value, traceback):
        self.output.stdin.close()
        return self.output.wait()


color_mapping = ColorMapping()

with Pdf(sys.argv[1], sys.argv[2]) as pdf:
    for line in pdf.read():
        pdf.write(color_mapping(line))

color_mapping.output_log()
