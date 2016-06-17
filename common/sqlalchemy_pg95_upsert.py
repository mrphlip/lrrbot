# https://bitbucket.org/robin900/sqlalchemy/branch/ticket_3529

# This is the MIT license: http://www.opensource.org/licenses/mit-license.php
#
# Copyright (c) 2005-2016 the SQLAlchemy authors and contributors <see AUTHORS file>.
# SQLAlchemy is a trademark of Michael Bayer.
#
# Permission is hereby granted, free of charge, to any person obtaining a copy of this
# software and associated documentation files (the "Software"), to deal in the Software
# without restriction, including without limitation the rights to use, copy, modify, merge,
# publish, distribute, sublicense, and/or sell copies of the Software, and to permit persons
# to whom the Software is furnished to do so, subject to the following conditions:
#
# The above copyright notice and this permission notice shall be included in all copies or
# substantial portions of the Software.
#
# THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR IMPLIED,
# INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY, FITNESS FOR A PARTICULAR
# PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE AUTHORS OR COPYRIGHT HOLDERS BE LIABLE
# FOR ANY CLAIM, DAMAGES OR OTHER LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR
# OTHERWISE, ARISING FROM, OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER
# DEALINGS IN THE SOFTWARE.

"""
.. _postgresql_insert_on_conflict:

INSERT...ON CONFLICT (Upsert)
------------------------------

Starting with version 9.5, PostgreSQL allows "upserts" (update or insert)
of rows into a table via the ``INSERT`` statement's ``ON CONFLICT`` clause.
PostgreSQL will first attempt to insert a row; if a unique constraint would be
violated because a row already exists with those unique values, the optional
``ON CONFLICT`` clause specifies how to handle the constraint violation:
either by skipping the insertion of that row (``ON CONFLICT DO NOTHING``),
or by instead performing an update of the already existing row, either with
values from the row being inserted or literal values.

The dialect recognizes the ``postgresql_on_conflict`` keyword argument
to :class:`.Insert`, :meth:`.Table.insert`, and other ``INSERT`` expression
builders.

Most commonly, ``ON CONFLICT`` is used to perform an update of the already
existing row if there is a primary key constraint violated, using the values
of the row proposed for insert. Use the value `'update'` for the keyword argument:

    table.insert(postgresql_on_conflict='update').\\
        values(key_column='existing_value', other_column='foo')

and the SQL compiler will produce an ``ON CONFLICT`` clause that performs
``DO UPDATE SET...`` for every column value in the ``VALUES`` clause that
is not a primary key column for the target table. The produced SQL will use the primary key
columns as the "conflict target" in the ``ON CONFLICT`` clause. This usage
requires that the targeted table have at least one column participating
in a `PrimaryKeyConstraint`.

`ON CONFLICT` is also commonly used to skip inserting a row entirely
if any conflict occurs. To do this, use the value 'nothing' for the keyword argument:

    table.insert(postgresql_on_conflict='nothing').\\
        values(key_column='existing_value', other_column='foo')

Less commonly, you may need to specify which of several unique constraints on a table
should be used to determine if an insert conflict exists. In these cases, use
the :class:`.DoNothing` or :class:`.DoUpdate` object, and pass one of the following
to indicate the "conflict target" constraint:

* a single Column object or string with the column's name
* a list or tuple of several Column objects or name strings
* a :class:`.PrimaryKeyConstraint`, :class:`.UniqueConstraint`,
  or :class:`.postgresql.ExcludeConstraint` object representing
  the unique constraint to target.

If you use :class:`.DoUpdate`, you need to specify which columns on the existing row
to set with values from the row proposed for insert. Use the
:meth:`.DoUpdate.set_with_excluded` chaining method to do so, passing a variable
set of Column or Column name string arguments for the columns to set using
the special `excluded` alias representing the row proposed for insertion:

    from common.sqlalchemy_pg95_upsert import DoUpdate, DoNothing
    from sqlalchemy.schema import UniqueConstraint

    unique_constr = UniqueConstraint(table.c.username)
    update_action = DoUpdate(unique_constr).set_with_excluded('key_column', 'other_column')

    table.insert(postgresql_on_conflict=update_action).\\
        .values(key_column='existing_value', other_column='foo')

Other, more sophisticated forms of ``ON CONFLICT`` are possible, especially
in what can be put in `SET ...` clauses, but they are
not yet supported or documented by the dialect. Use text-based statements
for more advanced ``ON CONFLICT`` clauses.

For more information on the PostgreSQL feature, see the
``ON CONFLICT` section of the `INSERT` statement in the PostgreSQL docs
<http://www.postgresql.org/docs/current/static/sql-insert.html#SQL-ON-CONFLICT>`_.
"""

import sqlalchemy.dialects.postgresql.base
from sqlalchemy.sql import compiler, expression, crud
from sqlalchemy import util
from sqlalchemy.sql.expression import ClauseElement, ColumnClause, ColumnElement
from sqlalchemy.ext.compiler import compiles
from sqlalchemy.exc import CompileError
from sqlalchemy.schema import UniqueConstraint, PrimaryKeyConstraint, Index
from collections import Iterable

ISINSERT = util.symbol('ISINSERT')
ISUPDATE = util.symbol('ISUPDATE')
ISDELETE = util.symbol('ISDELETE')

def _setup_crud_params(compiler, stmt, local_stmt_type, **kw):
	restore_isinsert = compiler.isinsert
	restore_isupdate = compiler.isupdate
	restore_isdelete = compiler.isdelete

	should_restore = (
		restore_isinsert or restore_isupdate or restore_isdelete
	) or len(compiler.stack) > 1

	if local_stmt_type is ISINSERT:
		compiler.isupdate = False
		compiler.isinsert = True
	elif local_stmt_type is ISUPDATE:
		compiler.isupdate = True
		compiler.isinsert = False
	elif local_stmt_type is ISDELETE:
		if not should_restore:
			compiler.isdelete = True
	else:
		assert False, "ISINSERT, ISUPDATE, or ISDELETE expected"

	try:
		if local_stmt_type in (ISINSERT, ISUPDATE):
			return crud._get_crud_params(compiler, stmt, **kw)
	finally:
		if should_restore:
			compiler.isinsert = restore_isinsert
			compiler.isupdate = restore_isupdate
			compiler.isdelete = restore_isdelete

def visit_insert(self, insert_stmt, asfrom=False, **kw):
	toplevel = not self.stack

	self.stack.append({
		'correlate_froms': set(),
		"asfrom_froms": set(),
		"selectable": insert_stmt
	})

	crud_params = _setup_crud_params(self, insert_stmt, ISINSERT, **kw)

	if not crud_params and \
			not self.dialect.supports_default_values and \
			not self.dialect.supports_empty_insert:
		raise exc.CompileError("The '%s' dialect with current database version settings does not "
		                       "support empty inserts." % self.dialect.name)

	if insert_stmt._has_multi_parameters:
		if not self.dialect.supports_multivalues_insert:
			raise exc.CompileError("The '%s' dialect with current database version settings does "
			                       "not support in-place multirow inserts." % self.dialect.name)
		crud_params_single = crud_params[0]
	else:
		crud_params_single = crud_params

	preparer = self.preparer
	supports_default_values = self.dialect.supports_default_values

	text = "INSERT "

	if insert_stmt._prefixes:
		text += self._generate_prefixes(insert_stmt, insert_stmt._prefixes, **kw)

	text += "INTO "
	table_text = preparer.format_table(insert_stmt.table)

	if insert_stmt._hints:
		dialect_hints, table_text = self._setup_crud_hints(insert_stmt, table_text)
	else:
		dialect_hints = None

	text += table_text

	if crud_params_single or not supports_default_values:
		text += " (%s)" % ', '.join([preparer.format_column(c[0]) for c in crud_params_single])

	if self.returning or insert_stmt._returning:
		returning_clause = self.returning_clause(insert_stmt,
		                                         self.returning or insert_stmt._returning)

		if self.returning_precedes_values:
			text += " " + returning_clause
	else:
		returning_clause = None

	if insert_stmt.select is not None:
		text += " %s" % self.process(self._insert_from_select, **kw)
	elif not crud_params and supports_default_values:
		text += " DEFAULT VALUES"
	elif insert_stmt._has_multi_parameters:
		text += " VALUES %s" % (
			", ".join(
				"(%s)" % (', '.join(c[1] for c in crud_param_set))
				for crud_param_set in crud_params
			)
		)
	else:
		text += " VALUES (%s)" % ', '.join([c[1] for c in crud_params])

	on_conflict_option = resolve_on_conflict_option(
		insert_stmt.dialect_options['postgresql']['on_conflict'],
		crud_params_single
	)
	if on_conflict_option is not None:
		text += " " + self.process(on_conflict_option)

	if returning_clause and not self.returning_precedes_values:
		text += " " + returning_clause

	if self.ctes and toplevel:
		text = self._render_cte_clause() + text

	self.stack.pop(-1)

	if asfrom:
		return "(" + text + ")"
	else:
		return text

class _EXCLUDED:
	pass

def resolve_on_conflict_option(option_value, crud_columns):
	if option_value is None:
		return None
	if isinstance(option_value, OnConflictAction):
		return option_value
	if str(option_value) == 'update':
		if not crud_columns:
			raise CompileError("Cannot compile postgresql_on_conflict='update' option when no insert columns are available")
		crud_table_pk = crud_columns[0][0].table.primary_key
		if not crud_table_pk.columns:
			raise CompileError("Cannot compile postgresql_on_conflict='update' option when no target table has no primary key column(s)")
		return DoUpdate(crud_table_pk.columns.values()).set_with_excluded(
			*[c[0] for c in crud_columns if not crud_table_pk.contains_column(c[0])]
		)
	if str(option_value) == 'nothing':
		return DoNothing()

class OnConflictAction(ClauseElement):
	def __init__(self, conflict_target):
		super(OnConflictAction, self).__init__()
		self.conflict_target = conflict_target

class DoUpdate(OnConflictAction):
	def __init__(self, conflict_target):
		super(DoUpdate, self).__init__(ConflictTarget(conflict_target))
		if not self.conflict_target.contents:
			raise ValueError("conflict_target may not be None or empty for DoUpdate")
		self.values_to_set = {}

	def set_with_excluded(self, *columns):
		for col in columns:
			if not isinstance(col, (ColumnClause, str)):
				raise ValueError("column arguments must be ColumnClause objects or str object with column name: %r" % col)
			self.values_to_set[col] = _EXCLUDED
		return self

	def set(self, **columns):
		for col, value in columns.items():
			if not isinstance(value, ColumnElement):
				raise ValueError("value arguments must be ColumnElement objects: %r" % value)
			self.values_to_set[col] = value
		return self

class DoNothing(OnConflictAction):
	def __init__(self, conflict_target=None):
		super(DoNothing, self).__init__(ConflictTarget(conflict_target) if conflict_target else None)

class ConflictTarget(ClauseElement):
	"""
	A ConflictTarget represents the targeted constraint that will be used to determine
	when a row proposed for insertion is in conflict and should be handled as specified
	in the OnConflictAction.

	A target can be one of the following:

	- A column or list of columns, either column objects or strings, that together
	  represent a unique or primary key constraint on the table. The compiler
	  will produce a list like `(col1, col2, col3)` as the conflict target SQL clause.

	- A single PrimaryKeyConstraint or UniqueConstraint object representing the constraint
	  used to detect the conflict. If the object has a :attr:`.name` attribute,
	  the compiler will produce `ON CONSTRAINT constraint_name` as the conflict target
	  SQL clause. If the constraint lacks a `.name` attribute, a list of its
	  constituent columns, like `(col1, col2, col3)` will be used.

	- An single :class:`Index` object representing the index used to detect the conflict.
	  Use this in place of the Constraint objects mentioned above if you require
	  the clauses of a conflict target specific to index definitions -- collation,
	  opclass used to detect conflict, and WHERE clauses for partial indexes.
	"""
	def __init__(self, contents):
		if isinstance(contents, (str, ColumnClause)):
			self.contents = (contents,)
		elif isinstance(contents, (list, tuple)):
			if not contents:
				raise ValueError("list of column arguments cannot be empty")
			for c in contents:
				if not isinstance(c, (str, ColumnClause)):
					raise ValueError("column arguments must be ColumnClause objects or str object with column name: %r" % c)
			self.contents = tuple(contents)
		elif isinstance(contents, (PrimaryKeyConstraint, UniqueConstraint, Index)):
			self.contents = contents
		else:
			raise ValueError(
				"ConflictTarget contents must be single Column/str, "
				"sequence of Column/str; or a PrimaryKeyConsraint, UniqueConstraint, or Index")

@compiles(ConflictTarget)
def compile_conflict_target(conflict_target, compiler, **kw):
	target = conflict_target.contents
	if isinstance(target, (PrimaryKeyConstraint, UniqueConstraint)):
		fmt_cnst = None
		if target.name is not None:
			fmt_cnst = compiler.preparer.format_constraint(target)
		if fmt_cnst is not None:
			return "ON CONSTRAINT %s" % fmt_cnst
		else:
			return "(" + (", ".join(compiler.preparer.format_column(i) for i in target.columns.values())) + ")"
	if isinstance(target, (str, ColumnClause)):
		return "(" + compiler.preparer.format_column(target) + ")"
	if isinstance(target, (list, tuple)):
		return "(" + (", ".join(compiler.preparer.format_column(i) for i in target)) + ")"
	if isinstance(target, Index):
		# columns required first.
		ops = target.dialect_options["postgresql"]["ops"]
		text = "(%s)" \
				% (
					', '.join([
						compiler.process(
							expr.self_group()
							if not isinstance(expr, ColumnClause)
							else expr,
							include_table=False, literal_binds=True) +
						(
							(' ' + ops[expr.key])
							if hasattr(expr, 'key')
							and expr.key in ops else ''
						)
						for expr in target.expressions
					])
				)

		whereclause = target.dialect_options["postgresql"]["where"]

		if whereclause is not None:
			where_compiled = compiler.process(
				whereclause, include_table=False,
				literal_binds=True)
			text += " WHERE " + where_compiled
		return text

@compiles(DoUpdate)
def compile_do_update(do_update, compiler, **kw):
	compiled_cf = compiler.process(do_update.conflict_target)
	if not compiled_cf:
		raise CompileError("Cannot have empty conflict_target")
	text = "ON CONFLICT %s DO UPDATE" % compiled_cf
	if not do_update.values_to_set:
		raise CompileEror("Cannot have empty set of values to SET in DO UPDATE")
	names = []
	for col, value in do_update.values_to_set.items():
		fmt_name = compiler.preparer.format_column(col) if isinstance(col, ColumnClause) else compiler.preparer.format_column(None, name=col)
		if value is _EXCLUDED:
			fmt_value = "excluded.%s" % fmt_name
		elif isinstance(value, ColumnElement):
			fmt_value = compiler.process(value)
		else:
			raise CompileError("Value to SET in DO UPDATE of unsupported type: %r" % value)
		names.append("%s = %s" % (fmt_name, fmt_value))
	text += (" SET " + ", ".join(names))
	return text

@compiles(DoNothing)
def compile_do_nothing(do_nothing, compiler, **kw):
	if do_nothing.conflict_target is not None:
		return "ON CONFLICT %s DO NOTHING" % compiler.process(do_nothing.conflict_target)
	else:
		return "ON CONFLICT DO NOTHING"


sqlalchemy.dialects.postgresql.base.PGCompiler.visit_insert = visit_insert

for cls, args in sqlalchemy.dialects.postgresql.base.PGDialect.construct_arguments:
	if cls == expression.Insert:
		args["on_conflict"] = None
		break
else:
	sqlalchemy.dialects.postgresql.base.PGDialect.construct_arguments.append((
		expression.Insert, {"on_conflict": None}
	))
