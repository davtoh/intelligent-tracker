#!/usr/bin/env python
# -*- coding: utf-8 -*-
# (C) 2017 David Toro <davsamirtor@gmail.com>

# import built-in modules
import sys
import json
from json import JSONEncoder

# special variables
# __all__ = []
__author__ = "David Toro"
# __copyright__ = "Copyright 2017, The <name> Project"
# __credits__ = [""]
__license__ = "GPL"
# __version__ = "1.0.0"
__maintainer__ = "David Toro"
__email__ = "davsamirtor@gmail.com"
# __status__ = "Pre-release"

### JSON support
# these methods were not packed into a class to prevent customization
# thus setting an standard for dev extended json files

# create json support variables
extended_json_classes = {}
extended_json_watched_classes = {}
# this is implemented to be readable only and
# to set the dev extended json protocol
json_class_id = "__json_class__"  # field in json file for object class name
json_class_data = "__json_data__"  # field in json file for object data
json_class_module = "__json_module__"  # field in json file for object module
json_enco_name = "__json_enco__"  # name of encoding method in supporting class
json_deco_name = "__json_deco__"  # name of decoding method in supporting class


def get_obj_name(obj):
    # this should return the same as class_obj.__name__ from it instance obj
    try:
        return obj.__class__.__name__
    except AttributeError:
        return type(obj).__name__


def get_obj_module_name(obj):
    try:
        return obj.__module__  # for new-style
    except AttributeError:
        return type(obj).__module__  # for old-style


def register_json_class(class_obj, compatibility_name=None):
    extended_json_classes[class_obj.__name__] = class_obj
    if compatibility_name is not None:
        if not isinstance(compatibility_name, str):
            raise TypeError("compatibility_name must be string")
        extended_json_classes[compatibility_name] = class_obj


def register_json_watcher(class_obj, enco=None, deco=None):
    extended_json_watched_classes[class_obj.__name__] = (class_obj, enco, deco)


# register tuple watcher
# by default dev extended json files support tuple
# but they can be deactivated by removing the tuple watcher.
register_json_watcher(tuple, deco=tuple)


class DEVJSONEncoder(JSONEncoder):
    """
    Extended json decoder with support for instance classes with
    encoding methods.
    """
    # https://stackoverflow.com/a/3768975/5288758
    # https://docs.python.org/2/library/json.html

    def encode(self, obj):
        # https://stackoverflow.com/a/15721641/5288758
        def hint_tuples(item):
            if isinstance(item, tuple):
                return self.default(item)  # serialize with default
            if isinstance(item, list):
                return [hint_tuples(e) for e in item]  # walk list for tuples
            else:
                return item

        return super(DEVJSONEncoder, self).encode(hint_tuples(obj))

    def default(self, o):
        class_name = get_obj_name(o)
        module_name = get_obj_module_name(o)
        try:
            # process if is a extended class
            return {json_class_data: getattr(o, json_enco_name)(),  # get object data
                    json_class_id: class_name,  # get object class
                    json_class_module: module_name  # get module
                    }
        except AttributeError:
            # watched classes
            try:
                if class_name in extended_json_watched_classes:
                    enco = extended_json_watched_classes[class_name][1]
                    if enco is None:
                        data = o
                    else:
                        try:
                            data = enco(o)
                        except Exception as e:
                            raise type(e)(f"{e}. Watcher encoder failed") from e
                    return {json_class_data: data,  # get object data
                            json_class_id: class_name,  # get object class
                            json_class_module: module_name  # get module
                            }
            except Exception as e:
                raise type(e)(
                    f"{e}. Watched object of class '{class_name}' could not be "
                    f"json serialized"
                ) from e

            # special case
            # if tuple is in register_json_watcher it can be handled there
            # it gives freedom to the user to return tuple original behaviour
            if class_name == "tuple":
                return o

            return JSONEncoder.default(self, o)


def object_hook_DEVJSONDecoder(json_object):
    """
    object_hook compatible with DEVJSONEncoder

    :param json_object:
    :return:
    """
    # is it a extended object?
    try:
        custom_class_name = json_object[json_class_id]
        json_data = json_object[json_class_data]
        module_name = json_object[json_class_module]
    except KeyError:
        return json_object

    # try to find extended object class to recreate
    recreate = None
    recreate_method = " "
    to_unpack = False
    try:
        cls = extended_json_classes[custom_class_name]
        recreate_method += "extended list"
    except KeyError:

        # special case "tuple"
        if custom_class_name == "tuple":
            recreate = tuple
        elif custom_class_name in extended_json_watched_classes:
            # find in watched classes
            recreate, _, deco = extended_json_watched_classes[custom_class_name]
            if deco is None:
                to_unpack = True
            else:
                recreate = deco
            recreate_method += "watched list"
        else:
            # if not found in priority find in general modules
            cls_list = []
            for module_path in (i for i in sys.modules.keys() if module_name in i):
                cls = getattr(sys.modules[module_path], custom_class_name, None)
                if cls is not None:
                    cls_list.append(cls)
            if len(cls_list) == 0:
                raise ValueError(
                    "Object of class '{}' could not be found. "
                    "Make sure to register it.".format(custom_class_name))
            elif len(cls_list) > 1:
                raise ValueError(
                    "Multiple inferred '{}' objects classes in {}. "
                    "Make sure to register it.".format(custom_class_name, cls_list))
            else:
                cls = cls_list[0]
            recreate_method += "modules"

    if recreate is None:
        # ensure class has method
        try:
            recreate = getattr(cls, json_deco_name)  # custom recreation method
            recreate_method = "{} in{}".format(json_deco_name, recreate_method)
        except AttributeError:
            recreate = cls  # class __init__ method
            recreate_method = "__init__ in" + recreate_method
            to_unpack = True
    else:
        recreate_method = "DECO in" + recreate_method

    # try to recreate object
    try:
        if to_unpack:
            if isinstance(json_data, dict):
                # unpack dictionary
                return recreate(**json_data)
            else:
                # unpack iterable
                return recreate(*json_data)
        else:
            # provide data "as is"
            return recreate(json_data)
    except Exception as e:
        raise ValueError(f"{e}. Object of class '{custom_class_name}' could not be recreated "
                         f"from '{recreate_method}' method") from e


def save_configuration(path, data, indent=2, separators=(',', ': '),
                       cls=DEVJSONEncoder, **kwargs):
    """
    Save dev extended json serialization.

    :param path: save path
    :param data: custom data
    :param indent: 2
    :param separators: (',', ': ')
    :param cls: DEVJSONEncoder
    :param kwargs: additional arguments for json.dump
    :return:
    """
    json_data = json.dumps(data,
                       indent=indent,  # organize data by indent
                       separators=separators,  # prevent whitespace
                       cls=cls,
                       **kwargs
                       )
    # save only if serialization was successful
    with open(path, "w") as f:
        f.write(json_data)


def load_configuration(path, data=None, object_hook=object_hook_DEVJSONDecoder,
                       cls_enco=DEVJSONEncoder, **kwargs):
    """
    Load dev extended json file with default data if file is not found.

    :param path: load and save path
    :param data: any data supported by the extended json format
            implemented by dev
    :param object_hook: object_hook_DEVJSONDecoder
    :param cls_enco: DEVJSONEncoder
    :param kwargs: additional arguments for json.load
    :return: deserialized json data
    """
    try:
        with open(path, "r") as f:
            loaded = json.load(f, object_hook=object_hook, **kwargs)
    except IOError:
        if data is not None:
            save_configuration(path, data, cls=cls_enco)
        with open(path, "r") as f:
            loaded = json.load(f, object_hook=object_hook, **kwargs)
    return loaded