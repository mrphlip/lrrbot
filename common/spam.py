import confusables
import re

def compile_rule(rule):
	pattern_type = rule.get('pattern_type', 'regex')
	if pattern_type == 'text':
		return re.compile(re.escape(rule['re']))
	elif pattern_type == 'confusables':
		return re.compile(confusables.confusable_regex(rule['re']))
	elif pattern_type == 'regex':
		return re.compile(rule['re'])
	else:
		raise NotImplementedError(f"pattern of type {pattern_type}")
