# -*- coding: utf-8 -*-
import argparse
import random
import json
import string
import html

from rich.console import Console

from madhac.Logger import Logger
from madhac.template_filler.template import replace_template_variables


def get_parser():
    desc = 'This script converts a JSON schema to an HTML form.'
    author = 'Mad Hakker'
    description = desc + '\n' + author

    parser = argparse.ArgumentParser(
        description=description,
        formatter_class=argparse.RawTextHelpFormatter,
    )

    parser.add_argument(
        '-v',
        '--verbose',
        dest='verbosity',
        action='count',
        default=0,
        help='verbosity level (-v for verbose, -vv for debug)',
    )
    parser.add_argument(
        '-q',
        '--quiet',
        dest='quiet',
        action='store_true',
        default=False,
        help='Show no information at all',
    )

    parser.add_argument(
        'schema',
        help='JSON schema to convert',
    )
    parser.add_argument(
        'out',
        help='Output file',
    )

    parser.add_argument(
        '--mapping',
        help='Mapping file',
        default='./mappings/simple_mapping.json'
    )

    parser.add_argument(
        '--tag',
        help='HTML comment to look for inserting the resulting HTML content. Use with the --insert option.',
        default='<!-- j2f -->'
    )
    parser.add_argument(
        '--insert',
        action='store_true',
        help='Insert in the output file after the tag comment instead of overwriting file'
    )

    return parser


def get_options():
    return get_parser().parse_args()


def get_quote():
    quotes = [
        'It\'s no use going back to yesterday, because I was a different person then.',
        'We\'re all mad here.',
        'Curiouser and curiouser!',
        'I don\'t think -- " "Then you shouldn\'t talk.',
        'Your hair wants cutting',
        'Not all who wander are lost.',
        'I am not crazy; my reality is just different from yours.',
    ]
    return random.choice(quotes)


class JMapping():
    def __init__(self, mapping) -> None:
        self.mapping = mapping

    def _map(self, type, vars):
        """Uses the mapping to return the resulting HTML content.
        type - Type of mapping
        vars - Variables to pass to the template
        """
        if type not in self.mapping:
            raise Exception(f'No mapping for type: {type}')
        return self.mapping[type]


class JState():
    def __init__(self, jroot, jmap: JMapping) -> None:
        """
        jroot - Root JSON object
        """
        self.jroot = jroot
        self.jmap = jmap
        self.depth = 0

    def deep(self):
        self.depth += 1

    def high(self):
        self.depth -= 1

    def ref(self, ref):
        """Resolve indirect reference.
        """
        path = ref.split('/')
        if path[0] != '#':
            raise ParsingError(self, 'Cannot resolve references outside document')
        current = self.jroot
        for i, elt in enumerate(path[1:], 2):
            if elt in current:
                current = current[elt]
            else:
                raise ParsingError(self, f'Bad reference: {ref}\tUnknown element: {elt}')
        return current

    def rand_id(self):
        return ''.join(random.choice(string.ascii_lowercase) for i in range(6))

    def html(self, type: str, vars):
        """Returns the HTML content with the replaced template values.
        """
        # TODO(tquema): Handle indentation correctly
        lines = self.jmap._map(type, vars)

        def rec_html(rec_vars, lines):
            """Recursive function that returns the HTML of a line mapping.
            """
            # Concatenation of all lines
            all_lines = []
            for line in lines:
                # If the line is a string, just run the template function on it
                if isinstance(line, str):
                    html = replace_template_variables(line, rec_vars)
                    all_lines.append(html)

                # Otherwise, the line is a function that we have to execute
                # "if" function
                elif 'if' in line:
                    # Check for required values
                    if 'html' not in line:
                        raise MappingError(f'Missing HTML template for if function in type "{type}"')
                    if 'cond' not in line:
                        raise MappingError(f'Missing condition for if function in type "{type}"')
                    if 'cmp' not in line:
                        raise MappingError(f'Missing compared value for if function in type "{type}"')

                    # Apply if function
                    # TODO(tquema): Allow for more conditions
                    if line['cond'] == '=':
                        # Interpret "if" and "cmp"
                        if_left = replace_template_variables(line['if'], rec_vars)
                        if_right = replace_template_variables(line["cmp"], rec_vars)
                        logger.debug(f'cmp {if_left} == {if_right}')
                        if if_left == if_right:
                            # Condition OK: use lines in "html"
                            all_lines.append(rec_html(rec_vars, line['html']))
                        else:
                            # Condition KO: use lines in "else" (if any)
                            if 'else' in line:
                                all_lines.append(rec_html(rec_vars, line['else']))
                            # Otherwise, do nothing
                    else:
                        raise MappingError(f'Unknown condition "{line["cond"]}" in type "{type}"')

                # "for" function
                elif 'for' in line:
                    # Check for required values
                    if 'html' not in line:
                        raise MappingError(f'Missing HTML template for for-loop in type "{type}"')
                    if line['for'] not in rec_vars:
                        raise MappingError(f'Unknown variable: {line["for"]}')
                    if not isinstance(rec_vars[line['for']], list):
                        raise MappingError(f'Not a iterable variable: {line["for"]}')

                    # Inside for-loop variable
                    if 'as' in line:
                        floop_as = line['as']
                    else:
                        floop_as = 'f-elt'
                    # Resulting lines after the for-loop
                    res_html = []
                    # Enumerate on the given variable
                    for i, elt in enumerate(rec_vars[line['for']]):
                        # Provide additional template variables
                        template_vars = {
                            # 'f-i': str(i),
                            floop_as: elt,
                        } | rec_vars
                        # Parse each line with the added template variables
                        html = rec_html(template_vars, line['html'])
                        res_html.append(replace_template_variables(html, template_vars))
                    all_lines.append('\n'.join(res_html))

            return '\n'.join(all_lines)

        return rec_html(vars, lines)


class ParsingError(Exception):
    def __init__(self, jstate: JState, msg: str, obj='', *args: object) -> None:
        super().__init__(f'Depth: {jstate.depth}\t{msg}\t{str(obj)}', *args)
        self.jstate = jstate


class MappingError(Exception):
    pass


def extract_vars(jstate: JState, obj):
    """Extract global variables.
    """
    description = html.escape(obj['description']) if 'description' in obj else ''
    if 'title' in obj:
        title = html.escape(obj['title'])
    elif description:
        title = description
    else:
        title = 'Missing title'
    return {
        'id': jstate.rand_id(),
        'title': title,
        'description': description,
    }


def parse(jstate: JState, obj):
    """Call the corresponding parsing function regarding the type of the current observed object.
    """
    # Handle indirect reference
    if '$ref' in obj:
        obj = jstate.ref(obj['$ref'])

    if 'type' not in obj:
        raise ParsingError(jstate, 'Missing type information')

    MAP_TYPES = {
        'object': parse_object,
        'array': parse_array,
        'string': parse_string,
        'integer': parse_integer,
        'number': parse_integer,
        'boolean': parse_boolean,
        'null': parse_null,
    }

    t = obj['type']
    if t in MAP_TYPES:
        jstate.deep()
        return MAP_TYPES[t](jstate, obj)

    raise ParsingError(jstate, f'Unknown type: {t}')


def parse_object(jstate: JState, obj):
    """Parses the object and return the corresponding HTML.
    """
    if 'properties' in obj:
        properties = [
            parse(jstate, obj['properties'][property])
            for property in obj['properties']
        ]
        template_vars = extract_vars(jstate, obj) | {
            'properties': properties,
        }
        jstate.high()
        return jstate.html('object', template_vars)

    if 'patternProperties' in obj:
        return '<p><b>PATTERN PROPERTIES</b></p>'

    logger.warning(str(ParsingError(jstate, 'Missing properties in object', obj)))
    return ''


def parse_array(jstate: JState, obj):
    """Parses the array and return the corresponding HTML.
    """
    if 'items' not in obj:
        raise ParsingError(jstate, 'Missing items in array', obj)

    template_vars = extract_vars(jstate, obj) | {
        'new-elt': parse(jstate, obj['items']),
    }
    jstate.high()
    return jstate.html('array', template_vars)


def parse_string(jstate: JState, obj):
    """Parses a string.
    """
    template_vars = extract_vars(jstate, obj) | {
        'default': obj['default'] if 'default' in obj else '',
    }
    if 'enum' in obj:
        template_vars |= {
            'values': obj['enum'],
        }
        return jstate.html('string_enum', template_vars)
    return jstate.html('string', template_vars)


def parse_boolean(jstate: JState, obj):
    """Parses a boolean.
    """
    template_vars = extract_vars(jstate, obj) | {
        'checked': 'checked' if 'default' in obj and obj['default'] else '',
        'default': obj['default'] if 'default' in obj else '',
    }
    return jstate.html('boolean', template_vars)


def parse_integer(jstate: JState, obj):
    """Parses an integer.
    """
    template_vars = extract_vars(jstate, obj) | {
        'default': obj['default'] if 'default' in obj else '',
    }
    return jstate.html('integer', template_vars)


def parse_null(jstate: JState, obj):
    """Parses a null type.
    """
    template_vars = extract_vars(jstate, obj) | {
    }
    return jstate.html('null', template_vars)


def main(options, logger, console):
    # Load json schema
    with open(options.schema, 'r') as fin:
        schema = json.load(fin)
        # TODO(tquema): Ensure the format of the schema is correct

    # Load mapping
    with open(options.mapping, 'r') as fin:
        data = json.load(fin)
        jmap = JMapping(data['mapping'])

    # Parse
    jstate = JState(schema, jmap)
    try:
        html = parse(jstate, schema)
        # Write output file
        if options.insert:
            with open(options.out, 'r') as fin:
                lines = fin.readlines()
            tag_start = -1
            tag_end = -1
            for i, line in enumerate(lines):
                if options.tag in line:
                    if tag_start < 0:
                        tag_start = i + 1
                    elif tag_end < 0:
                        tag_end = i
                        break
            if tag_start < 0:
                raise Exception('No start tag in output file')
            if tag_end < 0:
                raise Exception('No end tag in output file')
            lines = lines[:tag_start] + lines[tag_end:]
            html += '\n'
            lines.insert(tag_start, html)
            with open(options.out, 'w') as fout:
                fout.write(''.join(lines))
        else:
            with open(options.out, 'w') as fout:
                fout.write(html)
    except ParsingError as e:
        logger.error(e)


if __name__ == "__main__":
    try:
        # Command line arguments
        options = get_options()

        console = Console()
        logger = Logger(console, options.verbosity, options.quiet)

        logger.info(get_quote())
        main(options, logger, console)
    except KeyboardInterrupt:
        logger.info('Terminating script...')
        raise SystemExit
