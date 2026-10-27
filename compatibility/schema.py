import json
from importlib.resources import files
import re

SCHEMAS = files('compatibility').joinpath('schema')


def validate(value, schema, path='$'):
    if 'enum' in schema and not any(type(value) is type(item) and value == item for item in schema['enum']):
        raise ValueError(path + ': invalid enum value')
    kind = schema.get('type')
    if isinstance(kind, list):
        for candidate in kind:
            try:
                validate(value, dict(schema, type=candidate), path)
                return value
            except ValueError:
                pass
        raise ValueError(path + ': invalid type')
    types = {'object': dict, 'array': list, 'string': str, 'integer': int, 'boolean': bool, 'null': type(None)}
    if kind and (type(value) is not types[kind]):
        raise ValueError(path + ': expected ' + kind)
    if isinstance(value, dict):
        for key in schema.get('required', []):
            if key not in value:
                raise ValueError(path + ': missing ' + key)
        for key, item in value.items():
            child = schema.get('properties', {}).get(key)
            if child is not None:
                validate(item, child, path + '.' + key)
            elif schema.get('additionalProperties') is False:
                raise ValueError(path + ': unknown field ' + key)
            elif isinstance(schema.get('additionalProperties'), dict):
                validate(item, schema['additionalProperties'], path + '.' + key)
    if isinstance(value, list):
        if len(value) < schema.get('minItems', 0):
            raise ValueError(path + ': empty array')
        for index, item in enumerate(value):
            validate(item, schema.get('items', {}), path + '[' + str(index) + ']')
    if isinstance(value, str) and 'pattern' in schema and not re.fullmatch(schema['pattern'], value):
        raise ValueError(path + ': invalid format')
    return value


def validate_document(value, name):
    return validate(value, json.loads(SCHEMAS.joinpath(name + '.schema.json').read_text()))
