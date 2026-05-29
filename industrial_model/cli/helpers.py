import pydantic.alias_generators as alias_generators


def to_pascal(value: str) -> str:
    return alias_generators.to_pascal(alias_generators.to_snake(value))


def to_snake(value: str) -> str:
    return alias_generators.to_snake(value)


def to_camel(value: str) -> str:
    return alias_generators.to_camel(value)
