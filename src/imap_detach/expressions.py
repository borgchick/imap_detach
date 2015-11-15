import parsimonious
import six
from imap_detach.utils import decode, to_datetime
from sqlite3.dbapi2 import Binary
from _datetime import datetime, timedelta

ParserSyntaxError = parsimonious.ParseError
ParserEvalError = parsimonious.exceptions.VisitationError

GRAMMAR=r""" # Test grammar
expr = space or space
or = and   more_or
more_or = ( space "|" space and )*
and = term  more_and
more_and = ( space "&" space term )*
term = not / value
not = "!" space value
value =  compare / bracketed / name
bracketed = "(" space expr space ")"
compare = contains / starts / ends / equals / smaller / smaller_equal/ bigger/ bigger_equal
contains  =  name space "~="  space literal
starts  =  name space "^="  space literal
ends  =  name space "$="  space literal
equals =  name space "="  space any_literal
smaller =  name space "<"  space numeric_literal
bigger =  name space ">"  space numeric_literal
smaller_equal =  name space "<="  space numeric_literal
bigger_equal =  name space ">="  space numeric_literal
name       = ~"[a-z]+"
numeric_literal = date / number
any_literal = date / number / literal
literal    = "\"" chars "\""
number =  ~"\d+"
date = ~"\d{4}-\d{1,2}-\d{1,2}(:?\ \d{1,4}:\d{1,2})?"
space    = " "*
chars = ~"[^\"]*"

"""

def grammar():
    return parsimonious.Grammar(GRAMMAR)

class EvalError(Exception):
    def __init__(self, text, pos=0):
        super(EvalError, self).__init__(text+ ' at position %d'%pos)
        
        
def extract_err_msg(e):
    if isinstance(e, ParserEvalError):
        return e.args[0]
    
    return str(e)
        
        


class SimpleEvaluator(parsimonious.NodeVisitor):
    def __init__(self, ctx, strict=True):
        self.grammar=grammar()
        self._ctx=ctx
        self._strict=strict
    
    @property    
    def context(self):
        return self._ctx
    
    @context.setter
    def context(self, ctx):
        self._ctx = ctx        
    
    def visit_name(self, node, chidren):
        if node.text in self._ctx :
            val=self._ctx[node.text]
            
            return val
        elif self._strict:
            raise EvalError('Unknown variable %s'%node.text, node.start)
        else:
            return ''
    
    def visit_literal(self,node, children):
        return children[1]
    
    def visit_number(self, node, children):
        return int(node.text)
    
    def visit_date(self, node, children):
        return to_datetime(node.text)
           
        
    def visit_chars(self, node, children):
        return node.text
    
    def binary(fn):  # @NoSelf
        def _inner(self, node, children):
            if isinstance(children[0], bool):
                raise EvalError('Variable is boolean, should not be used here %s'% node.text, node.start)
            return fn(self, node, children)
        return _inner
    
    def number_or_date(fn):  # @NoSelf
        def _inner(self, node, children):
            if not isinstance(children[0], (int, datetime)):
                raise EvalError('Applicable only to number or datetime: %s'% node.text, node.start)
            return fn(self, node, children)
        return _inner
    
    def string(fn):  # @NoSelf
        def _inner(self,node, children):
            if not isinstance(children[0], (six.string_types)+(six.binary_type,)):
                raise EvalError('Applicable only to strings: %s'% node.text, node.start)
            a=decode(children[0]).lower()
            b=decode(children[-1]).lower()
            return fn(self, node, [a,b])
        return _inner
    
    @binary
    @string
    def visit_contains(self, node, children):
        return children[0].find(children[-1]) > -1
    
    @binary
    @string
    def visit_starts(self, node, children):
        return children[0].startswith(children[-1])
    
    @binary
    @string
    def visit_ends(self, node, children):
        return children[0].endswith(children[-1])
    
    @binary
    def visit_equals(self, node, children):
        a=children[0]
        b=children[-1]
        if isinstance(b, datetime) and b.hour ==0 and b.minute ==0:
                a=datetime(a.year,a.month, a.day)
        return a == b
    
    @binary
    @number_or_date
    def visit_smaller(self, node, children):
        return children[0] < children[-1]
    
    @binary
    @number_or_date
    def visit_smaller_equal(self, node, children):
        a=children[0]
        b=children[-1]
#         if isinstance(b, datetime) and b.hour ==0 and b.minute ==0:
#                 a=datetime(a.year,a.month, a.day) +timedelta(hours=23, minutes=59, seconds=59)
        return a <= b
    
    @binary
    @number_or_date
    def visit_bigger(self, node, children):
        return children[0] > children[-1]
    
    @binary
    @number_or_date
    def visit_bigger_equal(self, node, children):
        return children[0] >= children[-1]
   
    def visit_expr(self, node, children):
        return children[1]
    
    def visit_or(self, node, children):
        return children[0] or children[1] 
    
    def visit_more_or(self,node, children):
        return any(children)
    
    def visit_and(self, node, children):
        return children[0] and (True if children[1] is None else children[1])
    
    def visit_more_and(self, node, children):
        return all(children)
        
    def visit_not(self, node, children):
        return not children[-1]
    
    def visit_bracketed(self, node, children):
        return children[2]
    
    def generic_visit(self, node, children):
        if children:
            return children[-1]
