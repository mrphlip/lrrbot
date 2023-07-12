import email.parser
import textwrap

DOCSTRING_IMPLICIT_PREFIX = """Content-Type: multipart/message; boundary=command

--command"""
DOCSTRING_IMPLICIT_SUFFIX = "\n--command--"

def parse_docstring(docstring):
	if docstring is None:
		docstring = ""
	docstring = DOCSTRING_IMPLICIT_PREFIX + textwrap.dedent(docstring) + DOCSTRING_IMPLICIT_SUFFIX
	return email.parser.Parser().parsestr(docstring)

def encode_docstring(docstring):
	docstring = str(docstring).rstrip()
	assert docstring.startswith(DOCSTRING_IMPLICIT_PREFIX)
	assert docstring.endswith(DOCSTRING_IMPLICIT_SUFFIX)
	return docstring[len(DOCSTRING_IMPLICIT_PREFIX):-len(DOCSTRING_IMPLICIT_SUFFIX)]

def add_header(doc, name, value):
	for part in doc.walk():
		if part.get_content_maintype() != "multipart":
			part[name] = value
	return doc
