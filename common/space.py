SPACE = "\u200B"

def monkey_patch_urlize():
	import jinja2.utils
	import re

	jinja2.utils._word_split_re = re.compile(r'([\s%s]+)' % SPACE)
