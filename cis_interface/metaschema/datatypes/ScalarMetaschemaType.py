import numpy as np
import copy
import base64
from cis_interface import units
from cis_interface.metaschema.datatypes import register_type
from cis_interface.metaschema.datatypes.MetaschemaType import MetaschemaType
from cis_interface.metaschema.datatypes.FixedMetaschemaType import (
    create_fixed_type_class)
from cis_interface.metaschema.properties import ScalarMetaschemaProperties


@register_type
class ScalarMetaschemaType(MetaschemaType):
    r"""Type associated with a scalar."""

    name = 'scalar'
    description = 'A scalar value with or without units.'
    properties = MetaschemaType.properties + ['subtype', 'precision', 'units']
    definition_properties = MetaschemaType.definition_properties + ['subtype']
    metadata_properties = (MetaschemaType.metadata_properties
                           + ['subtype', 'precision', 'units'])
    python_types = ScalarMetaschemaProperties._all_python_scalars

    @classmethod
    def validate(cls, obj):
        r"""Validate an object to check if it could be of this type.

        Args:
            obj (object): Object to validate.

        Returns:
            bool: True if the object could be of this type, False otherwise.

        """
        if super(ScalarMetaschemaType, cls).validate(obj):
            dtype = ScalarMetaschemaProperties.data2dtype(obj)
            for k in ScalarMetaschemaProperties._valid_numpy_types:
                if dtype.name.startswith(k):
                    return True
        return False
        
    @classmethod
    def encode_data(cls, obj, typedef):
        r"""Encode an object's data.

        Args:
            obj (object): Object to encode.
            typedef (dict): Type definition that should be used to encode the
                object.

        Returns:
            string: Encoded object.

        """
        arr = cls.to_array(obj)
        bytes = arr.tobytes()
        out = base64.encodestring(bytes).decode('ascii')
        return out

    @classmethod
    def decode_data(cls, obj, typedef):
        r"""Decode an object.

        Args:
            obj (string): Encoded object to decode.
            typedef (dict): Type definition that should be used to decode the
                object.

        Returns:
            object: Decoded object.

        """
        bytes = base64.decodestring(obj.encode('ascii'))
        dtype = ScalarMetaschemaProperties.definition2dtype(typedef)
        arr = np.fromstring(bytes, dtype=dtype)
        if 'shape' in typedef:
            arr = arr.reshape(typedef['shape'])
        return cls.from_array(arr, typedef['units'])

    @classmethod
    def transform_type(cls, obj, typedef=None):
        r"""Transform an object based on type info.

        Args:
            obj (object): Object to transform.
            typedef (dict): Type definition that should be used to transform the
                object.

        Returns:
            object: Transformed object.

        """
        if typedef is None:
            return obj
        typedef0 = cls.encode_type(obj)
        typedef1 = copy.deepcopy(typedef0)
        typedef1.update(**typedef)
        dtype = ScalarMetaschemaProperties.definition2dtype(typedef1)
        arr = cls.to_array(obj).astype(dtype)
        out = cls.from_array(arr, typedef0['units'])
        return units.convert_to(out, typedef1['units'])

    @classmethod
    def to_array(cls, obj):
        r"""Get np.array representation of the data.

        Args:
            obj (object): Object to get array for.

        Returns:
            np.ndarray: Array representation of object.

        """
        obj_nounits = units.get_data(obj)
        if isinstance(obj_nounits, np.ndarray):
            arr = obj_nounits
        else:
            dtype = ScalarMetaschemaProperties.data2dtype(obj_nounits)
            arr = np.array([obj_nounits], dtype=dtype)
        return arr
        
    @classmethod
    def from_array(cls, arr, unit_str=None):
        r"""Get object representation of the data.

        Args:
            arr (np.ndarray): Numpy array.
            unit_str (str, optional): Units that should be added to returned
                object.

        Returns:
            object: Object representation of the data in the input array.

        """
        if (cls.name not in ['1darray', 'ndarray']) and (arr.ndim > 0):
            out = arr[0]
        else:
            out = arr
        if unit_str is not None:
            out = units.add_units(out, unit_str)
        return out


# Dynamically create explicity scalar classes for shorthand
for t in ScalarMetaschemaProperties._valid_types.keys():
    create_fixed_type_class(t, 'A %s value with or without units.' % t,
                            ScalarMetaschemaType, {'subtype': t}, globals(),
                            python_types=ScalarMetaschemaProperties._python_scalars[t])
