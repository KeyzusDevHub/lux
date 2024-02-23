# AUTOGENERATED! DO NOT EDIT! File to edit: src/data_scrambler.ipynb (unless otherwise specified).

__all__ = ['DataScrambler']

# Cell
from .data import Data
from .reading import Reading
from .value import Value
from .instance import Instance
from typing import List
import random

# Cell
class DataScrambler:
    @staticmethod
    def scramble_data(original: Data, conf: List['Configuration']) -> Data:
        atts = original.get_attributes()
        inst = []
        name = original.get_name() + '_scrambled'

        # create random for different configurations
        idxs_for_scrambling = {}
        for c in conf:
            idxs_for_scrambling[c] = DataScrambler.get_indices(
                int(c.to_scramble * len(original.get_instances())), len(original.get_instances()))

        instance_idx = 0
        for i in original.get_instances():
            new_instance = Instance()
            scrambled = []
            for c in conf:
                if instance_idx in idxs_for_scrambling[c]:
                    to_scramble = i.get_reading_for_attribute(c.att_name)
                    scrambled_readings = []

                    # scramble, add to scrambled
                    best_val = to_scramble.get_most_probable()
                    scrambled_readings.append(Value(best_val.get_name(), best_val.get_confidence() - c.mistake_epsilon))
                    to_be_selected = []
                    for v in to_scramble.get_values():
                        if v == best_val:
                            continue
                        if c.uniform:
                            scrambled_readings.append(Value(v.get_name(),
                                v.get_confidence() + c.mistake_epsilon/(len(to_scramble.get_values()) - 1)))
                        else:
                            to_be_selected.append(v)

                    if to_be_selected:
                        rand = random.randint(0, len(to_be_selected) - 1)
                        winner = to_be_selected[rand]
                        scrambled_readings.append(
                            Value(winner.get_name(), winner.get_confidence() + c.mistake_epsilon))
                        to_be_selected.remove(winner)

                    scrambled_readings += to_be_selected

                    # now, we have complete reading in scrambled reading, add it to scrambled
                    scrambled.append(Reading(original.get_attribute_of_name(c.att_name), scrambled_readings))

            # add scrambled and not scrambled to new instance - remember to keep the order of the original data
            for orig_reading in i.get_readings():
                # find in scrambled
                was_scrambled = False
                for scr_reading in scrambled:
                    if scr_reading.get_base_att().get_name() == orig_reading.get_base_att().get_name():
                        new_instance.add_reading(scr_reading)
                        was_scrambled = True
                        break
                if not was_scrambled:
                    new_instance.add_reading(orig_reading)

            # add instance
            inst.append(new_instance)
            instance_idx += 1

        return Data(name, atts, inst)

    @staticmethod
    def get_indices(number: int, length: int) -> List[int]:
        indices = [i for i in range(length)]
        random.shuffle(indices)
        return indices[:number]

    class Configuration:
        def __init__(self, att_name: str, to_scramble: float, mistake_epsilon: float, uniform: bool):
            """
            Data scrambler configuration.

            Parameters
            ----------
            att_name : str
                Attribute name which values has to be made uncertain.
            to_scramble : float
                How much data (0-1) has to be scrambled.
            mistake_epsilon : float
                By what factor the data have to be scrambled.
                In other words, how much certainty has to be subtracted from the real
                value and assigned to other values.
            uniform : bool
                Does the probability have to be split between other values uniformly,
                or should one of the value be picked  randomly as 'favorable mistake'.
            """
            self.att_name = att_name
            self.to_scramble = to_scramble
            self.mistake_epsilon = mistake_epsilon
            self.uniform = uniform