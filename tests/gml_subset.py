"""A small interpreter for the GML subset used by MistriMulti, for developer tests only.

The game is the only real GML runtime, and it cannot run here. This interpreter parses every mod file
(a syntax check) and executes the engine-independent ones, such as MistriMultiEvents.gml, so that the
same simulation tests that check the Python reference model also check the GML source itself.

It is deliberately stricter than GameMaker where GameMaker would fail at runtime or behave in a way that
is easy to get wrong: reading an unset struct field, adding a string to a number, comparing a string with a
number, out-of-range array reads, using a non-Boolean/non-number as a condition, and assigning to an
undeclared variable (which GML would silently store on `self`) are all errors.
"""
import json
import math
import re

KEYWORDS = {
    "function", "var", "if", "else", "for", "while", "do", "until", "repeat", "switch", "case", "default",
    "return", "break", "continue", "exit", "try", "catch", "finally", "throw", "with", "new", "delete",
    "true", "false", "undefined", "static", "enum", "and", "or", "not", "mod", "div", "global", "self", "other",
}

TOKEN = re.compile(r"""
    (?P<ws>[ \t\r\n]+)
  | (?P<comment>//[^\n]*|/\*.*?\*/)
  | (?P<macro>\#macro[ \t]+[A-Za-z_][A-Za-z0-9_]*[^\n]*)
  | (?P<number>0x[0-9A-Fa-f]+|\$[0-9A-Fa-f]+|\d+\.\d*|\.\d+|\d+)
  | (?P<string>"(?:[^"\\\n]|\\.)*")
  | (?P<name>[A-Za-z_][A-Za-z0-9_]*)
  | (?P<op>\[\$|\[\?|\[@|\[\||\[\#|\?\?=|\?\?|<<=|>>=|<<|>>|<=|>=|==|!=|&&|\|\||\+\+|--|\+=|-=|\*=|/=|%=|&=|\|=|\^=|[-+*/%<>=!~&|^?:;,.(){}\[\]])
""", re.S | re.X)


class GmlError(Exception):
    """A GML runtime error (what the engine would report as a crash)."""


class GmlSyntaxError(Exception):
    pass


class GStruct(dict):
    """A GML struct. Plain dict storage; `.field` reads are strict, `[$ "k"]` reads are lenient."""
    __hash__ = object.__hash__

    def __eq__(self, other):
        return self is other

    def __ne__(self, other):
        return self is not other


class GArray(list):
    __hash__ = object.__hash__

    def __eq__(self, other):
        return self is other

    def __ne__(self, other):
        return self is not other


class Tok:
    __slots__ = ("kind", "value", "line")

    def __init__(self, kind, value, line):
        self.kind, self.value, self.line = kind, value, line

    def __repr__(self):
        return f"{self.kind}:{self.value}@{self.line}"


def tokenize(source, macros):
    tokens = []
    pos = 0
    line = 1
    while pos < len(source):
        m = TOKEN.match(source, pos)
        if not m:
            raise GmlSyntaxError(f"line {line}: unexpected character {source[pos]!r}")
        kind = m.lastgroup
        text = m.group()
        if kind == "macro":
            parts = text.split(None, 2)
            name = parts[1]
            body = parts[2] if len(parts) > 2 else ""
            macros[name] = tokenize(body, macros)[:-1]
        elif kind not in ("ws", "comment"):
            if kind == "name" and text in KEYWORDS:
                kind = "kw"
            if kind == "name" and text in macros:
                for t in macros[text]:
                    tokens.append(Tok(t.kind, t.value, line))
            else:
                tokens.append(Tok(kind, text, line))
        line += text.count("\n")
        pos = m.end()
    tokens.append(Tok("eof", None, line))
    return tokens


def unescape(text):
    body = text[1:-1]
    out = []
    i = 0
    while i < len(body):
        c = body[i]
        if c == "\\":
            i += 1
            e = body[i]
            if e == "u":
                out.append(chr(int(body[i + 1:i + 5], 16)))
                i += 4
            else:
                out.append({"n": "\n", "t": "\t", "r": "\r", "\\": "\\", '"': '"', "b": "\b", "f": "\f"}.get(e, e))
        else:
            out.append(c)
        i += 1
    return "".join(out)


# ---- parser --------------------------------------------------------------------------------------------

BINARY = {
    "??": 1, "||": 2, "or": 2, "&&": 3, "and": 3, "|": 4, "^": 5, "&": 6, "==": 7, "!=": 7,
    "<": 8, "<=": 8, ">": 8, ">=": 8, "<<": 9, ">>": 9, "+": 10, "-": 10, "*": 11, "/": 11, "mod": 11, "%": 11, "div": 11,
}
ASSIGN = {"=", "+=", "-=", "*=", "/=", "%=", "&=", "|=", "^=", "??=", "<<=", ">>="}


class Parser:
    def __init__(self, tokens, filename):
        self.t = tokens
        self.i = 0
        self.filename = filename

    def peek(self, offset=0):
        return self.t[self.i + offset]

    def at(self, value, offset=0):
        tok = self.t[self.i + offset]
        return tok.kind in ("op", "kw") and tok.value == value

    def next(self):
        tok = self.t[self.i]
        self.i += 1
        return tok

    def expect(self, value):
        tok = self.next()
        if tok.value != value or tok.kind not in ("op", "kw"):
            raise GmlSyntaxError(f"{self.filename}:{tok.line}: expected {value!r}, found {tok.value!r}")
        return tok

    def name(self):
        tok = self.next()
        if tok.kind != "name":
            raise GmlSyntaxError(f"{self.filename}:{tok.line}: expected a name, found {tok.value!r}")
        return tok.value

    def program(self):
        body = []
        while self.peek().kind != "eof":
            body.append(self.statement())
        return body

    def block(self):
        self.expect("{")
        body = []
        while not self.at("}"):
            if self.peek().kind == "eof":
                raise GmlSyntaxError(f"{self.filename}: unclosed block")
            body.append(self.statement())
        self.expect("}")
        return ("block", body)

    def semicolon(self):
        while self.at(";"):
            self.next()

    def statement(self):
        tok = self.peek()
        line = tok.line
        if self.at(";"):
            self.next()
            return ("block", [])
        if self.at("{"):
            return self.block()
        if self.at("function") and self.peek(1).kind == "name":
            self.next()
            name = self.name()
            fn = self.function_rest(name)
            return ("function", name, fn, line)
        if self.at("var") or self.at("static"):
            self.next()
            decls = []
            while True:
                name = self.name()
                value = None
                if self.at("="):
                    self.next()
                    value = self.expression()
                decls.append((name, value))
                if not self.at(","):
                    break
                self.next()
            self.semicolon()
            return ("var", decls, line)
        if self.at("if"):
            self.next()
            cond = self.expression()
            if self.at("then"):
                self.next()
            then = self.statement()
            other = None
            if self.at("else"):
                self.next()
                other = self.statement()
            return ("if", cond, then, other, line)
        if self.at("for"):
            self.next()
            self.expect("(")
            init = None if self.at(";") else self.simple_statement()
            self.expect(";")
            cond = None if self.at(";") else self.expression()
            self.expect(";")
            step = None if self.at(")") else self.simple_statement()
            self.expect(")")
            return ("for", init, cond, step, self.statement(), line)
        if self.at("while"):
            self.next()
            cond = self.expression()
            return ("while", cond, self.statement(), line)
        if self.at("repeat"):
            self.next()
            count = self.expression()
            return ("repeat", count, self.statement(), line)
        if self.at("do"):
            self.next()
            body = self.statement()
            self.expect("until")
            cond = self.expression()
            self.semicolon()
            return ("do", body, cond, line)
        if self.at("with"):
            self.next()
            target = self.expression()
            return ("with", target, self.statement(), line)
        if self.at("switch"):
            self.next()
            value = self.expression()
            self.expect("{")
            cases = []
            while not self.at("}"):
                if self.at("case"):
                    self.next()
                    match = self.expression()
                    self.expect(":")
                    cases.append((match, []))
                elif self.at("default"):
                    self.next()
                    self.expect(":")
                    cases.append((None, []))
                else:
                    if not cases:
                        raise GmlSyntaxError(f"{self.filename}:{self.peek().line}: statement before case")
                    cases[-1][1].append(self.statement())
            self.expect("}")
            return ("switch", value, cases, line)
        if self.at("return"):
            self.next()
            value = None
            if not self.at(";") and not self.at("}"):
                value = self.expression()
            self.semicolon()
            return ("return", value, line)
        if self.at("break") or self.at("continue") or self.at("exit"):
            word = self.next().value
            self.semicolon()
            return (word, line)
        if self.at("throw"):
            self.next()
            value = self.expression()
            self.semicolon()
            return ("throw", value, line)
        if self.at("delete"):
            self.next()
            value = self.expression()
            self.semicolon()
            return ("delete", value, line)
        if self.at("try"):
            self.next()
            body = self.block()
            name = None
            handler = None
            final = None
            if self.at("catch"):
                self.next()
                self.expect("(")
                name = self.name()
                self.expect(")")
                handler = self.block()
            if self.at("finally"):
                self.next()
                final = self.block()
            return ("try", body, name, handler, final, line)
        node = self.simple_statement()
        self.semicolon()
        return node

    def simple_statement(self):
        line = self.peek().line
        if self.at("var"):
            self.next()
            name = self.name()
            self.expect("=")
            return ("var", [(name, self.expression())], line)
        if self.at("++") or self.at("--"):
            op = self.next().value
            target = self.unary()
            return ("incdec", target, op, line)
        target = self.expression()
        tok = self.peek()
        if tok.kind == "op" and tok.value in ASSIGN:
            self.next()
            value = self.expression()
            self.check_target(target)
            return ("assign", target, tok.value, value, line)
        if self.at("++") or self.at("--"):
            op = self.next().value
            self.check_target(target)
            return ("incdec", target, op, line)
        if target[0] not in ("call", "new", "postfix"):
            raise GmlSyntaxError(f"{self.filename}:{line}: expression is not a statement")
        return ("expr", target, line)

    def check_target(self, target):
        if target[0] not in ("name", "member", "index", "access", "global"):
            raise GmlSyntaxError(f"{self.filename}: cannot assign to {target[0]}")

    def function_rest(self, name):
        self.expect("(")
        params = []
        while not self.at(")"):
            pname = self.name()
            default = None
            if self.at("="):
                self.next()
                default = self.expression()
            params.append((pname, default))
            if self.at(","):
                self.next()
        self.expect(")")
        if self.at(":"):  # constructor inheritance
            self.next()
            self.name()
            self.call_args()
        if self.at("constructor"):
            self.next()
        if self.peek().kind == "name" and self.peek().value == "constructor":
            self.next()
        body = self.block()
        return ("fn", name, params, body)

    def expression(self, minimum=0):
        left = self.unary()
        while True:
            tok = self.peek()
            if tok.kind in ("op", "kw") and tok.value == "?" and minimum <= 0:
                self.next()
                then = self.expression()
                self.expect(":")
                other = self.expression()
                left = ("ternary", left, then, other)
                continue
            if tok.kind not in ("op", "kw") or tok.value not in BINARY:
                return left
            prec = BINARY[tok.value]
            if prec < minimum:
                return left
            self.next()
            right = self.expression(prec + 1)
            left = ("binary", tok.value, left, right, tok.line)

    def unary(self):
        tok = self.peek()
        if tok.kind in ("op", "kw") and tok.value in ("!", "-", "~", "not", "+"):
            self.next()
            return ("unary", tok.value, self.unary(), tok.line)
        if self.at("++") or self.at("--"):
            op = self.next().value
            return ("preinc", op, self.unary(), tok.line)
        return self.postfix(self.primary())

    def call_args(self):
        self.expect("(")
        args = []
        while not self.at(")"):
            args.append(self.expression())
            if self.at(","):
                self.next()
            elif not self.at(")"):
                raise GmlSyntaxError(f"{self.filename}:{self.peek().line}: expected , or ) in call")
        self.expect(")")
        return args

    def postfix(self, node):
        while True:
            tok = self.peek()
            if self.at("("):
                node = ("call", node, self.call_args(), tok.line)
            elif self.at("."):
                self.next()
                member = self.next()
                if member.kind not in ("name", "kw"):
                    raise GmlSyntaxError(f"{self.filename}:{member.line}: expected a member name")
                node = ("member", node, member.value, member.line)
            elif tok.kind == "op" and tok.value in ("[$", "[?", "[@", "[|", "[#"):
                self.next()
                key = self.expression()
                if tok.value == "[#":
                    self.expect(",")
                    self.expression()
                self.expect("]")
                node = ("access" if tok.value == "[$" else "index", node, key, tok.line)
            elif self.at("["):
                self.next()
                key = self.expression()
                if self.at(","):
                    raise GmlSyntaxError(f"{self.filename}:{tok.line}: 2D array syntax is not supported")
                self.expect("]")
                node = ("index", node, key, tok.line)
            else:
                return node

    def primary(self):
        tok = self.next()
        if tok.kind == "number":
            text = tok.value
            if text.startswith("0x"):
                return ("const", int(text, 16))
            if text.startswith("$"):
                return ("const", int(text[1:], 16))
            return ("const", float(text) if "." in text else int(text))
        if tok.kind == "string":
            return ("const", unescape(tok.value))
        if tok.kind == "kw":
            if tok.value == "true":
                return ("const", True)
            if tok.value == "false":
                return ("const", False)
            if tok.value == "undefined":
                return ("const", None)
            if tok.value == "global":
                return ("globalref", tok.line)
            if tok.value in ("self", "other"):
                return ("self", tok.line)
            if tok.value == "function":
                return ("lambda", self.function_rest(None))
            if tok.value == "new":
                ctor = self.primary()
                while self.at("."):
                    self.next()
                    ctor = ("member", ctor, self.name(), tok.line)
                return ("new", ctor, self.call_args(), tok.line)
        if tok.kind == "name":
            return ("name", tok.value, tok.line)
        if tok.kind == "op":
            if tok.value == "(":
                inner = self.expression()
                self.expect(")")
                return inner
            if tok.value == "[":
                items = []
                while not self.at("]"):
                    items.append(self.expression())
                    if self.at(","):
                        self.next()
                self.expect("]")
                return ("array", items)
            if tok.value == "{":
                fields = []
                while not self.at("}"):
                    key = self.next()
                    if key.kind == "string":
                        name = unescape(key.value)
                    elif key.kind in ("name", "kw"):
                        name = key.value
                    else:
                        raise GmlSyntaxError(f"{self.filename}:{key.line}: bad struct key {key.value!r}")
                    if self.at(":"):
                        self.next()
                        fields.append((name, self.expression()))
                    else:
                        fields.append((name, ("name", name, key.line)))
                    if self.at(","):
                        self.next()
                self.expect("}")
                return ("struct", fields)
        raise GmlSyntaxError(f"{self.filename}:{tok.line}: unexpected {tok.value!r}")


def parse(source, filename="<gml>", macros=None):
    macros = {} if macros is None else macros
    return Parser(tokenize(source, macros), filename).program()


# ---- evaluation ----------------------------------------------------------------------------------------

class Return(Exception):
    def __init__(self, value):
        self.value = value


class Break(Exception):
    pass


class Continue(Exception):
    pass


class Thrown(Exception):
    def __init__(self, value):
        self.value = value


class Function:
    def __init__(self, name, params, body, interp):
        self.name, self.params, self.body, self.interp = name, params, body, interp

    def __call__(self, *args):
        return self.interp.invoke(self, list(args))

    def __repr__(self):
        return f"<gml function {self.name}>"


def gml_type(value):
    if value is None:
        return "undefined"
    if isinstance(value, bool):
        return "bool"
    if isinstance(value, (int, float)):
        return "number"
    if isinstance(value, str):
        return "string"
    if isinstance(value, GArray) or isinstance(value, list):
        return "array"
    if isinstance(value, GStruct) or isinstance(value, dict):
        return "struct"
    if callable(value):
        return "method"
    return "unknown"


def number(value, what):
    if isinstance(value, bool):
        return int(value)
    if isinstance(value, (int, float)):
        return value
    raise GmlError(f"{what}: expected a number, got {gml_type(value)}")


def to_int(value, what):
    v = number(value, what)
    return int(round(v)) if isinstance(v, float) else v


def gml_string(value):
    if value is None:
        return "undefined"
    if isinstance(value, bool):
        return "1" if value else "0"
    if isinstance(value, (int, float)):
        if isinstance(value, float) and (math.isnan(value) or math.isinf(value)):
            return "nan" if math.isnan(value) else "inf"
        if value == math.floor(value) and abs(value) < 1e15:
            return str(int(value))
        return f"{value:.2f}"
    if isinstance(value, str):
        return value
    if isinstance(value, list):
        return "[ " + ",".join(gml_string(v) for v in value) + " ]"
    if isinstance(value, dict):
        return "{ " + " , ".join(f"{k} : {gml_string(v)}" for k, v in value.items()) + " }"
    return str(value)


def to_json(value):
    if value is None:
        return "null"
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, (int, float)):
        if value == math.floor(value) and abs(value) < 1e15:
            return str(int(value))
        return repr(float(value))
    if isinstance(value, str):
        return json.dumps(value, ensure_ascii=False)
    if isinstance(value, list):
        return "[" + ",".join(to_json(v) for v in value) + "]"
    if isinstance(value, dict):
        return "{" + ",".join(json.dumps(k, ensure_ascii=False) + ":" + to_json(v) for k, v in value.items()) + "}"
    raise GmlError(f"json_stringify: cannot serialise {gml_type(value)}")


def from_json(value):
    if isinstance(value, dict):
        out = GStruct()
        for k, v in value.items():
            out[k] = from_json(v)
        return out
    if isinstance(value, list):
        return GArray(from_json(v) for v in value)
    return value


def truthy(value, what="condition"):
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return value > 0.5
    raise GmlError(f"{what}: {gml_type(value)} is not a Boolean")


class Buffer:
    def __init__(self, size):
        self.data = bytearray()
        self.size = size
        self.pos = 0


class Interpreter:
    def __init__(self, builtins=None):
        self.functions = {}
        self.globals = GStruct()
        self.macros = {}
        self.builtins = dict(self.standard_builtins())
        if builtins:
            self.builtins.update(builtins)
        self.steps = 0

    def load(self, source, filename="<gml>"):
        program = parse(source, filename, self.macros)
        for node in program:
            if node[0] == "function":
                _, name, (_, _, params, body), _line = node
                self.functions[name] = Function(name, params, body, self)
        return program

    def call(self, name, *args):
        fn = self.functions.get(name)
        if fn is None:
            raise GmlError(f"no GML function {name}")
        return self.invoke(fn, list(args))

    # -- calls ------------------------------------------------------------------------------------------
    def invoke(self, fn, args):
        if len(args) > len(fn.params):
            raise GmlError(f"{fn.name}: {len(args)} arguments for {len(fn.params)} parameters")
        scope = {}
        for i, (pname, default) in enumerate(fn.params):
            if i < len(args) and args[i] is not None:
                scope[pname] = args[i]
            elif default is not None:
                scope[pname] = self.eval(default, scope)
            else:
                scope[pname] = args[i] if i < len(args) else None
        try:
            self.exec(fn.body, scope)
        except Return as r:
            return r.value
        return None

    def call_value(self, fn, args, line):
        if isinstance(fn, Function):
            return self.invoke(fn, args)
        if callable(fn):
            return fn(*args)
        raise GmlError(f"line {line}: {gml_type(fn)} is not callable")

    # -- statements -------------------------------------------------------------------------------------
    def exec(self, node, scope):
        self.steps += 1
        kind = node[0]
        if kind == "block":
            for stmt in node[1]:
                self.exec(stmt, scope)
        elif kind == "var":
            for name, value in node[1]:
                scope[name] = None if value is None else self.eval(value, scope)
        elif kind == "expr":
            self.eval(node[1], scope)
        elif kind == "assign":
            _, target, op, value, line = node
            if op == "=":
                self.store(target, self.eval(value, scope), scope, line)
            elif op == "??=":
                if self.eval(target, scope) is None:
                    self.store(target, self.eval(value, scope), scope, line)
            else:
                current = self.eval(target, scope)
                self.store(target, self.binary(op[:-1], current, self.eval(value, scope), line), scope, line)
        elif kind == "incdec":
            _, target, op, line = node
            current = number(self.eval(target, scope), f"line {line}: {op}")
            self.store(target, current + (1 if op == "++" else -1), scope, line)
        elif kind == "if":
            _, cond, then, other, line = node
            if truthy(self.eval(cond, scope), f"line {line}: if"):
                self.exec(then, scope)
            elif other is not None:
                self.exec(other, scope)
        elif kind == "for":
            _, init, cond, step, body, line = node
            if init is not None:
                self.exec(init, scope)
            while cond is None or truthy(self.eval(cond, scope), f"line {line}: for"):
                try:
                    self.exec(body, scope)
                except Break:
                    break
                except Continue:
                    pass
                if step is not None:
                    self.exec(step, scope)
        elif kind == "while":
            _, cond, body, line = node
            while truthy(self.eval(cond, scope), f"line {line}: while"):
                try:
                    self.exec(body, scope)
                except Break:
                    break
                except Continue:
                    pass
        elif kind == "repeat":
            _, count, body, line = node
            for _ in range(to_int(self.eval(count, scope), f"line {line}: repeat")):
                try:
                    self.exec(body, scope)
                except Break:
                    break
                except Continue:
                    pass
        elif kind == "do":
            _, body, cond, line = node
            while True:
                try:
                    self.exec(body, scope)
                except Break:
                    break
                except Continue:
                    pass
                if truthy(self.eval(cond, scope), f"line {line}: until"):
                    break
        elif kind == "switch":
            _, value, cases, line = node
            subject = self.eval(value, scope)
            matched = False
            try:
                for match, body in cases:
                    if not matched:
                        if match is None or self.equal(subject, self.eval(match, scope), line):
                            matched = True
                    if matched:
                        for stmt in body:
                            self.exec(stmt, scope)
                if not matched:
                    for i, (match, body) in enumerate(cases):
                        if match is None:
                            for _m, rest in cases[i:]:
                                for stmt in rest:
                                    self.exec(stmt, scope)
                            break
            except Break:
                pass
        elif kind == "return":
            raise Return(None if node[1] is None else self.eval(node[1], scope))
        elif kind == "exit":
            raise Return(None)
        elif kind == "break":
            raise Break()
        elif kind == "continue":
            raise Continue()
        elif kind == "throw":
            raise Thrown(self.eval(node[1], scope))
        elif kind == "try":
            _, body, name, handler, final, line = node
            try:
                self.exec(body, scope)
            except (GmlError, Thrown, ArithmeticError, TypeError, KeyError, IndexError, ValueError, AttributeError) as error:
                if handler is None:
                    raise
                scope[name] = error.value if isinstance(error, Thrown) else gml_string(str(error))
                self.exec(handler, scope)
            finally:
                if final is not None:
                    self.exec(final, scope)
        elif kind == "function":
            _, name, (_, _, params, body), _line = node
            self.functions[name] = Function(name, params, body, self)
        else:
            raise GmlError(f"statement {kind} is not supported by the test interpreter")

    def store(self, target, value, scope, line):
        kind = target[0]
        if kind == "name":
            name = target[1]
            if name not in scope:
                # An engine global (a macro such as MAXIMUM_REACHED_DUNGEON_LEVEL) a test provides as a plain value.
                if name in self.builtins and not callable(self.builtins[name]):
                    self.builtins[name] = value
                    return
                raise GmlError(f"line {line}: assignment to undeclared variable {name} (missing var?)")
            scope[name] = value
        elif kind == "member":
            obj = self.eval(target[1], scope)
            if isinstance(obj, GStruct) or (isinstance(obj, dict) and not isinstance(obj, GArray)):
                obj[target[2]] = value
            elif target[1][0] == "globalref":
                self.globals[target[2]] = value
            else:
                raise GmlError(f"line {line}: cannot set .{target[2]} on {gml_type(obj)}")
        elif kind == "access":
            obj = self.eval(target[1], scope)
            key = self.eval(target[2], scope)
            if not isinstance(obj, dict) or not isinstance(key, str):
                raise GmlError(f"line {line}: bad struct accessor assignment")
            obj[key] = value
        elif kind == "index":
            obj = self.eval(target[1], scope)
            index = to_int(self.eval(target[2], scope), f"line {line}: index")
            if not isinstance(obj, list) or index < 0:
                raise GmlError(f"line {line}: bad array assignment")
            while len(obj) <= index:
                obj.append(0)
            obj[index] = value
        else:
            raise GmlError(f"line {line}: cannot assign to {kind}")

    # -- expressions ------------------------------------------------------------------------------------
    def eval(self, node, scope):
        kind = node[0]
        if kind == "const":
            return node[1]
        if kind == "name":
            name = node[1]
            if name in scope:
                return scope[name]
            if name in self.functions:
                return self.functions[name]
            if name in self.builtins:
                return self.builtins[name]
            raise GmlError(f"line {node[2]}: unknown variable {name}")
        if kind == "member":
            base = node[1]
            if base[0] == "globalref":
                if node[2] not in self.globals:
                    raise GmlError(f"line {node[3]}: global.{node[2]} not set before reading")
                return self.globals[node[2]]
            obj = self.eval(base, scope)
            if isinstance(obj, dict):
                if node[2] not in obj:
                    raise GmlError(f"line {node[3]}: variable {node[2]} not set before reading")
                return obj[node[2]]
            raise GmlError(f"line {node[3]}: .{node[2]} on {gml_type(obj)}")
        if kind == "access":
            base = node[1]
            obj = self.globals if base[0] == "globalref" else self.eval(base, scope)
            key = self.eval(node[2], scope)
            if not isinstance(obj, dict) or not isinstance(key, str):
                raise GmlError(f"line {node[3]}: [$] needs a struct and a string key")
            return obj.get(key)
        if kind == "index":
            obj = self.eval(node[1], scope)
            index = to_int(self.eval(node[2], scope), f"line {node[3]}: index")
            if not isinstance(obj, list):
                raise GmlError(f"line {node[3]}: indexing {gml_type(obj)}")
            if index < 0 or index >= len(obj):
                raise GmlError(f"line {node[3]}: index {index} out of range 0..{len(obj) - 1}")
            return obj[index]
        if kind == "call":
            fn = self.eval(node[1], scope)
            args = [self.eval(a, scope) for a in node[2]]
            return self.call_value(fn, args, node[3])
        if kind == "binary":
            _, op, left, right, line = node
            if op in ("&&", "and"):
                return truthy(self.eval(left, scope), f"line {line}: &&") and truthy(self.eval(right, scope), f"line {line}: &&")
            if op in ("||", "or"):
                return truthy(self.eval(left, scope), f"line {line}: ||") or truthy(self.eval(right, scope), f"line {line}: ||")
            if op == "??":
                value = self.eval(left, scope)
                return self.eval(right, scope) if value is None else value
            return self.binary(op, self.eval(left, scope), self.eval(right, scope), line)
        if kind == "unary":
            _, op, operand, line = node
            value = self.eval(operand, scope)
            if op in ("!", "not"):
                return not truthy(value, f"line {line}: !")
            if op == "-":
                return -number(value, f"line {line}: unary -")
            if op == "+":
                return number(value, f"line {line}: unary +")
            return ~to_int(value, f"line {line}: ~")
        if kind == "ternary":
            return self.eval(node[2], scope) if truthy(self.eval(node[1], scope), "?:") else self.eval(node[3], scope)
        if kind == "array":
            return GArray(self.eval(item, scope) for item in node[1])
        if kind == "struct":
            out = GStruct()
            for key, value in node[1]:
                out[key] = self.eval(value, scope)
            return out
        if kind == "new":
            return self.call_value(self.eval(node[1], scope), [self.eval(a, scope) for a in node[2]], node[3])
        if kind == "lambda":
            _, name, params, body = node[1]
            return Function("<anonymous>", params, body, self)
        if kind == "globalref":
            return self.globals
        raise GmlError(f"expression {kind} is not supported by the test interpreter")

    def equal(self, a, b, line):
        if isinstance(a, str) != isinstance(b, str) and a is not None and b is not None:
            raise GmlError(f"line {line}: comparing {gml_type(a)} with {gml_type(b)}")
        if isinstance(a, (dict, list)) or isinstance(b, (dict, list)):
            return a is b
        return a == b

    def binary(self, op, a, b, line):
        where = f"line {line}: {op}"
        if op == "==":
            return self.equal(a, b, line)
        if op == "!=":
            return not self.equal(a, b, line)
        if op == "+":
            if isinstance(a, str) or isinstance(b, str):
                if not (isinstance(a, str) and isinstance(b, str)):
                    raise GmlError(f"{where}: adding {gml_type(a)} to {gml_type(b)}")
                return a + b
            return number(a, where) + number(b, where)
        if op in ("<", "<=", ">", ">="):
            if isinstance(a, str) and isinstance(b, str):
                x, y = a, b
            else:
                x, y = number(a, where), number(b, where)
            return {"<": x < y, "<=": x <= y, ">": x > y, ">=": x >= y}[op]
        if op == "-":
            return number(a, where) - number(b, where)
        if op == "*":
            return number(a, where) * number(b, where)
        if op == "/":
            divisor = number(b, where)
            if divisor == 0:
                raise GmlError(f"{where}: division by zero")
            result = number(a, where) / divisor
            return int(result) if result == int(result) and abs(result) < 1e15 else result
        if op in ("mod", "%"):
            divisor = number(b, where)
            if divisor == 0:
                raise GmlError(f"{where}: division by zero")
            return math.fmod(number(a, where), divisor) if isinstance(a, float) or isinstance(b, float) \
                else int(math.fmod(number(a, where), divisor))
        if op == "div":
            divisor = number(b, where)
            if divisor == 0:
                raise GmlError(f"{where}: division by zero")
            return int(number(a, where) / divisor)
        x, y = to_int(a, where), to_int(b, where)
        if op == "&":
            return x & y
        if op == "|":
            return x | y
        if op == "^":
            return x ^ y
        if op == "<<":
            return (x << y) & 0xFFFFFFFFFFFFFFFF if x >= 0 else x << y
        if op == ">>":
            return x >> y
        raise GmlError(f"{where}: unsupported operator")

    # -- the engine functions the tested files use --------------------------------------------------------
    def standard_builtins(self):
        def array_length(a):
            if not isinstance(a, list):
                raise GmlError("array_length: not an array")
            return len(a)

        def array_push(a, *values):
            if not isinstance(a, list):
                raise GmlError("array_push: not an array")
            a.extend(values)

        def array_delete(a, index, count):
            if not isinstance(a, list):
                raise GmlError("array_delete: not an array")
            index = to_int(index, "array_delete")
            del a[index:index + to_int(count, "array_delete")]

        def array_pop(a):
            if not isinstance(a, list):
                raise GmlError("array_pop: not an array")
            return a.pop() if a else None

        def array_create(size, value=0):
            return GArray([value] * to_int(size, "array_create"))

        def string_copy(text, index, count):
            if not isinstance(text, str):
                raise GmlError("string_copy: not a string")
            start = max(to_int(index, "string_copy"), 1) - 1
            return text[start:start + max(to_int(count, "string_copy"), 0)]

        def string_length(text):
            if not isinstance(text, str):
                raise GmlError("string_length: not a string")
            return len(text)

        def string_byte_length(text):
            if not isinstance(text, str):
                raise GmlError("string_byte_length: not a string")
            return len(text.encode("utf-8"))

        def string_char_at(text, index):
            if not isinstance(text, str):
                raise GmlError("string_char_at: not a string")
            index = to_int(index, "string_char_at")
            return text[index - 1] if 1 <= index <= len(text) else ""

        def json_parse(text):
            if not isinstance(text, str):
                raise GmlError("json_parse: not a string")
            try:
                return from_json(json.loads(text))
            except ValueError as error:
                raise GmlError(f"json_parse: {error}") from None

        def struct_exists(s, key):
            if not isinstance(s, dict):
                raise GmlError("struct_exists: not a struct")
            return key in s

        def struct_remove(s, key):
            if not isinstance(s, dict):
                raise GmlError("struct_remove: not a struct")
            s.pop(key, None)

        def struct_get_names(s):
            if not isinstance(s, dict):
                raise GmlError("struct_get_names: not a struct")
            return GArray(s.keys())

        def is_real(v):
            return isinstance(v, (int, float)) and not isinstance(v, bool)

        def buffer_create(size, kind, alignment):
            return Buffer(to_int(size, "buffer_create"))

        def buffer_write(buffer, kind, value):
            if kind == "text":
                buffer.data[buffer.pos:buffer.pos] = value.encode("utf-8")
                buffer.pos += len(value.encode("utf-8"))
            elif kind == "u8":
                buffer.data[buffer.pos:buffer.pos + 1] = bytes([to_int(value, "buffer_write") & 255])
                buffer.pos += 1
            else:
                raise GmlError("buffer_write: unsupported type")
            if len(buffer.data) > buffer.size:
                raise GmlError("buffer_write: fixed buffer overflow")

        def buffer_seek(buffer, base, offset):
            buffer.pos = to_int(offset, "buffer_seek")

        def buffer_read(buffer, kind):
            if kind != "u8":
                raise GmlError("buffer_read: unsupported type")
            if buffer.pos >= len(buffer.data):
                raise GmlError("buffer_read: outside the buffer")
            value = buffer.data[buffer.pos]
            buffer.pos += 1
            return value

        def no_op(*args):
            return None

        return {
            "array_length": array_length, "array_push": array_push, "array_delete": array_delete,
            "array_pop": array_pop, "array_create": array_create,
            "string": gml_string, "string_copy": string_copy, "string_length": string_length,
            "string_byte_length": string_byte_length, "string_char_at": string_char_at,
            "ord": lambda c: ord(c[0]) if isinstance(c, str) and c else 0,
            "string_delete": lambda s, i, n: s[:max(to_int(i, "string_delete"), 1) - 1] + s[max(to_int(i, "string_delete"), 1) - 1 + to_int(n, "string_delete"):],
            "string_digits": lambda s: "".join(c for c in s if c.isdigit()),
            "string_replace_all": lambda s, a, b: s.replace(a, b),
            "json_stringify": to_json, "json_parse": json_parse,
            "is_struct": lambda v: isinstance(v, dict), "is_array": lambda v: isinstance(v, list),
            "is_string": lambda v: isinstance(v, str), "is_real": is_real, "typeof": gml_type,
            "struct_exists": struct_exists, "struct_remove": struct_remove, "struct_get_names": struct_get_names,
            "floor": lambda v: math.floor(number(v, "floor")), "min": lambda *v: min(number(x, "min") for x in v),
            "max": lambda *v: max(number(x, "max") for x in v),
            "buffer_create": buffer_create, "buffer_write": buffer_write, "buffer_seek": buffer_seek,
            "buffer_read": buffer_read, "buffer_delete": no_op,
            "buffer_fixed": "fixed", "buffer_text": "text", "buffer_u8": "u8", "buffer_seek_start": "start",
            "mmapi_warn_rate_limited": no_op, "mmapi_log_info": no_op, "mmapi_log_warn": no_op,
            "mmapi_log_error": no_op,
        }
