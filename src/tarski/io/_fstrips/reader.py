"""
 The loader imports the AST visitor from the parser directory - this directory is autogenerated by the
 utils/parser appropriate scripts, and should not be manually modified.
"""
import copy
import logging

from antlr4 import FileStream, CommonTokenStream, InputStream
from antlr4.error.ErrorListener import ErrorListener

from .common import parse_number, process_requirements, create_sort
from ...errors import SyntacticError
from ...fstrips import DelEffect, AddEffect, FunctionalEffect, UniversalEffect, OptimizationMetric
from ...syntax import CompoundFormula, Connective, neg, Tautology, implies, exists, forall, Term, Interval
from ...syntax.builtins import get_predicate_from_symbol, get_function_from_symbol
from ...syntax.formulas import VariableBinding

from .parser.visitor import fstripsVisitor
from .parser.lexer import fstripsLexer
from .parser.parser import fstripsParser


class FStripsParser(fstripsVisitor):
    """
    The parser assumes that the domain file is visited _before_ the instance file
    """

    def parse_string(self, string, start_rule='pddlDoc'):
        """ Parse a given string starting from a given grammar rule """
        return self._parse_stream(InputStream(string), start_rule)

    def parse_file(self, filename, start_rule='pddlDoc'):
        """ Parse a given filename starting from a given grammar rule """
        return self._parse_stream(FileStream(filename), start_rule)

    def _parse_stream(self, filestream, start_rule='pddlDoc'):
        lexer = self._configure_error_handling(fstripsLexer(filestream))
        stream = CommonTokenStream(lexer)
        parser = self._configure_error_handling(fstripsParser(stream))

        assert hasattr(parser, start_rule)
        tree = getattr(parser, start_rule)()
        return tree, stream

    def _configure_error_handling(self, element):
        if self.error_handler is not None:
            # If necessary, _replace_ previous error handlers with the given one
            element.removeErrorListeners()
            element.addErrorListener(self.error_handler)
        return element

    def __init__(self, problem, raise_on_error=False):
        self.error_handler = ExceptionRaiserListener() if raise_on_error else None
        self.current_binding = None

        # Shortcuts
        self.problem = problem
        self.language = problem.language
        self.init = problem.init

        self.requirements = set()

    def visitDomainName(self, ctx):
        self.problem.domain_name = ctx.NAME().getText().lower()

    def visitProblemDecl(self, ctx):
        self.problem.name = ctx.NAME().getText().lower()

    def visitProblemDomain(self, ctx):
        domain_name_as_declared_in_instance = ctx.NAME().getText().lower()
        if domain_name_as_declared_in_instance != self.problem.domain_name:
            logging.warning('Domain names as declared in domain and instance files do not coincide: "{}" vs " {}"'.
                            format(self.problem.domain_name, domain_name_as_declared_in_instance))

    def visitRequireDef(self, ctx):
        for req_ctx in ctx.REQUIRE_KEY():
            requirement = req_ctx.getText().lower()
            self.requirements.add(requirement)

        process_requirements(self.requirements, self.language)

    def visitDeclaration_of_types(self, ctx):
        for typename, basename in self.visit(ctx.possibly_typed_name_list()):
            create_sort(self.language, typename, basename)

    def extract_namelist(self, ctx):
        return [name.getText().lower() for name in ctx.NAME()]

    def visitSimpleNameList(self, ctx):
        names = self.extract_namelist(ctx)
        return [(name, 'object') for name in names]

    def visitName_list_with_type(self, ctx):
        typename = ctx.typename().getText().lower()
        names = self.extract_namelist(ctx)
        return [(name, typename) for name in names]

    def visitComplexNameList(self, ctx):
        simple = self.visitSimpleNameList(ctx)
        derived = []
        for sub in ctx.name_list_with_type():
            derived += self.visit(sub)
        return simple + derived

    def visitSingle_predicate_definition(self, ctx):
        predicate = ctx.predicate().getText().lower()
        argument_types = [a.sort for a in self.visit(ctx.possibly_typed_variable_list())]
        return self.language.predicate(predicate, *argument_types)

    def visitUntypedVariableList(self, ctx):
        variables = [self.language.variable(name.getText().lower(), 'object') for name in ctx.VARIABLE()]
        return variables

    def visitTypedVariableList(self, ctx):
        untyped_var_names = [self.language.variable(name.getText().lower(), 'object') for name in ctx.VARIABLE()]
        typed_var_names = []
        for sub_ctx in ctx.variable_list_with_type():
            typed_var_names += self.visit(sub_ctx)
        return typed_var_names + untyped_var_names

    def visitVariable_list_with_type(self, ctx):
        typename = ctx.primitive_type().getText().lower()  # This is the type of all variables in the list
        return [self.language.variable(name.getText().lower(), typename) for name in ctx.VARIABLE()]

    def visitTyped_function_definition(self, ctx, return_type=None):
        return_type = return_type or ctx.primitive_type().getText().lower()
        name = ctx.logical_symbol_name().getText().lower()
        argument_types = [a.sort for a in self.visit(ctx.possibly_typed_variable_list())]
        return self.language.function(name, *argument_types, return_type)

    def visitUnTyped_function_definition(self, ctx):
        return self.visitTyped_function_definition(ctx, 'object')

    def visitTypeBoundsDefinition(self, ctx):
        typename = ctx.NAME().getText().lower()
        sort = self.language.get_sort(typename)
        if not isinstance(sort, Interval):
            raise RuntimeError("Attempt at bounding symbolic non-interval sort '{}'".format(sort))

        # Encode the bounds and set them into the sort
        lower = sort.encode(ctx.NUMBER(0).getText())
        upper = sort.encode(ctx.NUMBER(1).getText())
        sort.set_bounds(lower, upper)

    def visitObject_declaration(self, ctx):
        for o, t in self.visit(ctx.possibly_typed_name_list()):
            # TODO We might want to record elsewhere that these constants are
            # TODO required as per the PDDL spec to have fixed denotation
            self.language.constant(o, t)

    # For a fixed problem, there's no particular distinction btw domain constants and problem objects.
    visitConstant_declaration = visitObject_declaration

    def push_variables(self, variables, root=False):
        return ParserVariableContext(self, variables, root)

    def visitActionDef(self, ctx):
        name = ctx.actionName().getText().lower()
        params = self.visit(ctx.possibly_typed_variable_list())
        binding = VariableBinding(params)

        with self.push_variables(params, root=True) as _:
            precondition, effect = self.visit(ctx.actionDefBody())

        self.problem.action(name, binding, precondition, effect)

    def visitActionDefBody(self, ctx):
        prec = self.visit(ctx.precondition())
        eff = self.visit(ctx.effect())
        return prec, eff

    def visitTrivialPrecondition(self, ctx):
        return Tautology()

    def visitRegularPrecondition(self, ctx):
        return self.visit(ctx.goalDesc())

    def visitAtomicTermFormula(self, ctx):
        predicate_symbol = ctx.predicate().getText().lower()
        predicate = self.language.get_predicate(predicate_symbol)
        subterms = [self.visit(term_ctx) for term_ctx in ctx.term()]
        return predicate(*subterms)

    def visitTermGoalDesc(self, ctx):
        return self.visit(ctx.atomicTermFormula())

    def visitTermObject(self, ctx):
        name = ctx.NAME().getText().lower()
        return self.language.get_constant(name)

    def visitTermNumber(self, ctx):
        number = ctx.NUMBER().getText().lower()
        return parse_number(number, self.language)

    def _recover_variable_from_context(self, name):
        if self.current_binding is None:
            raise RuntimeError("Variable '{}' used declared outside variable binding".format(name))

        return self.current_binding.get(name)

    def visitTermVariable(self, ctx):
        variable_name = ctx.VARIABLE().getText().lower()
        return self._recover_variable_from_context(variable_name)

    def visitGenericFunctionTerm(self, ctx):
        symbol = ctx.logical_symbol_name().getText().lower()
        func = self.language.get_function(symbol)
        subterms = [self.visit(t) for t in ctx.term()]
        return func(*subterms)

    def visitBinaryArithmeticFunctionTerm(self, ctx):
        op = ctx.builtin_binary_function().getText().lower()
        subterms = [self.visit(t) for t in ctx.term()]
        lhs, rhs = subterms
        return self.language.dispatch_operator(get_function_from_symbol(op), Term, Term, lhs, rhs)
    #
    # def visitUnaryArithmeticFunctionTerm(self, ctx):
    #     func_name = ctx.builtin_unary_function().getText().lower()
    #     if func_name not in built_in_functional_symbols:
    #         raise SystemExit("Function {0} first seen used as a term in an atomic formula".format(func_name))
    #     if func_name == '-':
    #         return FunctionalTerm('*', [self.visit(ctx.term()), NumericConstant(-1)])
    #     return FunctionalTerm(func_name, [self.visit(ctx.term())])

    def visitAndGoalDesc(self, ctx):
        conjuncts = [self.visit(sub_ctx) for sub_ctx in ctx.goalDesc()]
        # The PDDL spec allows for and AND with zero or a single conjunct (e.g. (and p), which Tarski does (rightly) not
        # We thus treat those cases specially.
        if len(conjuncts) == 0:
            return Tautology
        elif len(conjuncts) == 1:
            return conjuncts[0]
        return CompoundFormula(Connective.And, conjuncts)

    def visitOrGoalDesc(self, ctx):
        conjuncts = [self.visit(sub_ctx) for sub_ctx in ctx.goalDesc()]
        return CompoundFormula(Connective.Or, conjuncts)

    def visitNotGoalDesc(self, ctx):
        return neg(self.visit(ctx.goalDesc()))

    def visitImplyGoalDesc(self, ctx):
        lhs = self.visit(ctx.goalDesc(0))
        rhs = self.visit(ctx.goalDesc(1))
        return implies(lhs, rhs)

    def _visit_quantified_formula(self, ctx):
        variables = self.visit(ctx.possibly_typed_variable_list())

        with self.push_variables(variables, root=False) as _:
            formula = self.visit(ctx.goalDesc())
        return variables, formula

    def _visit_quantified_effect(self, ctx):
        """ Universally-quantified effects are different to formulas in that they are shorthand
            for a list of effects """
        variables = self.visit(ctx.possibly_typed_variable_list())

        with self.push_variables(variables, root=False) as _:
            formula = self.visit(ctx.effect())
        return variables, formula

    def visitExistentialGoalDesc(self, ctx):
        variables, formula = self._visit_quantified_formula(ctx)
        return exists(*variables, formula)

    def visitUniversalGoalDesc(self, ctx):
        variables, formula = self._visit_quantified_formula(ctx)
        return forall(*variables, formula)

    def visitBuiltinBinaryAtom(self, ctx):
        op = ctx.builtin_binary_predicate().getText().lower()
        lhs = self.visit(ctx.term(0))
        rhs = self.visit(ctx.term(1))
        return self.language.dispatch_operator(get_predicate_from_symbol(op), Term, Term, lhs, rhs)

    def visitGoal(self, ctx):
        self.problem.goal = self.visit(ctx.goalDesc())

    def visitSingleEffect(self, ctx):
        # The effect might already be a list if it derives from a multiple conditional effect.
        # Otherwise, we turn it into a list
        effect = self.visit(ctx.single_effect())
        return effect if isinstance(effect, list) else [effect]

    def visitConjunctiveEffectFormula(self, ctx):
        return [self.visit(sub_ctx) for sub_ctx in ctx.single_effect()]

    def visitAtomicEffect(self, ctx):
        return self.visit(ctx.atomic_effect())

    def visitAddAtomEffect(self, ctx):
        return AddEffect(self.visit(ctx.atomicTermFormula()))

    def visitDeleteAtomEffect(self, ctx):
        return DelEffect(self.visit(ctx.atomicTermFormula()))

    def visitAssignConstant(self, ctx):
        return FunctionalEffect(self.visit(ctx.functionTerm()), self.visit(ctx.term()))

    def visitUniversallyQuantifiedEffect(self, ctx):
        variables, effect = self._visit_quantified_effect(ctx)
        return UniversalEffect(variables, effect)

    def visitSingleConditionalEffect(self, ctx):
        effect = self.visit(ctx.atomic_effect())
        effect.condition = self.visit(ctx.goalDesc())
        return effect

    def visitMultipleConditionalEffect(self, ctx):
        condition = self.visit(ctx.goalDesc())
        effects = [self.visit(sub_ctx) for sub_ctx in ctx.atomic_effect()]
        for eff in effects:
            eff.condition = condition  # We simply copy the condition in each effect

        return effects

    def visitInit(self, ctx):
        # i.e. simply visit all node children
        for element_ctx in ctx.init_element():
            self.visit(element_ctx)

    def visitInitPositiveLiteral(self, ctx):
        predicate, subterms = self.visit(ctx.flat_atom())
        self.init.add(predicate, *subterms)

    def visitInitNegativeLiteral(self, ctx):
        # No need to do anything here, as atoms are assumed by default to be false
        pass

    def visitInitFunctionAssignment(self, ctx):
        fun, subterms = self.visit(ctx.flat_term())
        value = self.visit(ctx.constant_name())
        self.init.setx(fun(*subterms), value)

    def visitFlat_atom(self, ctx):
        predicate = self.language.get_predicate(ctx.predicate().getText().lower())
        subterms = tuple(self.visit(term_ctx) for term_ctx in ctx.constant_name())
        return predicate, subterms

    def visitFlat_term(self, ctx):
        func_name = self.language.get_function(ctx.function_name().getText().lower())
        subterms = tuple(self.visit(term_ctx) for term_ctx in ctx.constant_name())
        return func_name, subterms

    def visitSymbolic_constant(self, ctx):
        return self.language.get_constant(ctx.NAME().getText().lower())

    def visitNumeric_constant(self, ctx):
        number = ctx.NUMBER().getText().lower()
        return number

    # def visitExtensionalConstraintGD(self, ctx):
    #     arg_list = []
    #     for fn_ctx in ctx.groundFunctionTerm():
    #         arg_list.append(self.visit(fn_ctx))
    #     return [Atom(ctx.EXTNAME().getText().lower(), arg_list)]

    def visitAlternativeAlwaysConstraint(self, ctx):
        return [self.visit(ctx.goalDesc())]

    def visitConjunctionOfConstraints(self, ctx):
        constraints = []
        for conGD_ctx in ctx.prefConGD():
            constraints += self.visit(conGD_ctx)
        return constraints

    def visitPlainConstraintList(self, ctx):
        constraints = []
        for conGD_ctx in ctx.conGD():
            constraints += self.visit(conGD_ctx)
        return constraints

    # def visitProbConstraints(self, ctx):
    #     self.constraints = Conjunction(self.visit(ctx.prefConGD()))

    def visitProblemMetric(self, ctx):
        opt_type = ctx.optimization().getText().lower()
        opt_expression = self.visit(ctx.metricFExp())
        self.problem.metric = OptimizationMetric(opt_expression, opt_type)

    def visitFunctionalExprMetric(self, ctx):
        return None, self.visit(ctx.functionTerm())

    def visitCompositeMetric(self, ctx):
        return self.visit(ctx.terminalCost()), self.visit(ctx.stageCost())

    def visitTerminalCost(self, ctx):
        return self.visit(ctx.functionTerm())

    def visitStageCost(self, ctx):
        return self.visit(ctx.functionTerm())

    def visitTotalTimeMetric(self, ctx):
        raise SystemExit("Unsupported feature: Minimize total-time metric is not supported")

    def visitIsViolatedMetric(self, ctx):
        raise SystemExit("Unsupported feature: Count of violated constraints metric is not supported")

    def visitAssignEffect(self, ctx):
        operation = ctx.assignOp().getText().lower()
        lhs = self.visit(ctx.functionTerm())
        rhs = self.visit(ctx.term())
        operator = {'scale-up': '*', 'scale-down': '/', 'increase': '+', 'decrease': '-'}[operation]
        rhs = self.language.dispatch_operator(get_function_from_symbol(operator), Term, Term, lhs, rhs)
        return FunctionalEffect(lhs, self.visit(ctx.term()), rhs)

    # ------------- PROCESS STUFF - UNREVISED -------------

    # def visitProcessAssignEffect(self, ctx):
    #     operation = ctx.processEffectOp().getText().lower()
    #     lhs = self.visit(ctx.functionTerm())
    #     rhs = self.visit(ctx.processEffectExp())
    #     if operation in ['assign', 'scale-up', 'scale-down']:
    #         raise SystemExit("Assign/scale up/scale down effects not allowed in processes")
    #     trans_op = {'increase': '+', 'decrease': '-'}
    #     new_rhs = FunctionalTerm(trans_op[operation], [lhs, rhs])
    #     return AssignmentEffect(lhs, new_rhs)  # This effectively normalizes effects
    #
    # def visitFunctionalProcessEffectExpr(self, ctx):
    #     return self.visit(ctx.processFunctionEff())
    #
    # def visitConstProcessEffectExpr(self, ctx):
    #     return self.visit(ctx.processConstEff())
    #
    # def visitVariableProcessEffectExpr(self, ctx):
    #     return self.visit(ctx.processVarEff())
    #
    # def visitProcessFunctionEff(self, ctx):
    #     return self.visit(ctx.functionTerm())
    #
    # def visitProcessConstEff(self, ctx):
    #     try:
    #         return NumericConstant(int(ctx.NUMBER().getText().lower()))
    #     except ValueError:
    #         return NumericConstant(float(ctx.NUMBER().getText().lower()))
    #
    # def visitProcessVarEff(self, ctx):
    #     variable_name = ctx.VARIABLE().getText().lower()
    #     return self._recover_variable_from_context(variable_name)
    #
    # def visitProcessSingleEffect(self, ctx):
    #     return ConjunctiveEffect([self.visit(ctx.processEffect())])
    #
    # def visitProcessConjunctiveEffectFormula(self, ctx):
    #     effects = []
    #     for sub_ctx in ctx.processEffect():
    #         effects.append(self.visit(sub_ctx))
    #     return ConjunctiveEffect(effects)
    #
    # def visitProcessDef(self, ctx):
    #     name = ctx.actionName().getText().lower()
    #     params = self.visit(ctx.possibly_typed_variable_list())
    #     self.current_params = params
    #     try:
    #         precondition, effect = self.visit(ctx.processDefBody())
    #     except UndeclaredVariable as error:
    #         raise SystemExit("Parsing process {}: undeclared variable {}".format(name, error))
    #     self.current_params = None
    #     process = Action(name, params, len(params), precondition, effect, None)
    #     self.processes.append(process)

    # def visitProcessDefBody(self, ctx):
    #     try:
    #         prec = self.visit(ctx.precondition())
    #     except UnresolvedVariableError as e:
    #         raise UndeclaredVariable('precondition', str(e))
    #     try:
    #         unnorm_eff = self.visit(ctx.processEffectList())
    #     except UnresolvedVariableError as e:
    #         raise UndeclaredVariable('effect', str(e))
    #     norm_eff = unnorm_eff.normalize()
    #     norm_eff_list = []
    #     add_effect(norm_eff, norm_eff_list)
    #
    #     return prec, norm_eff_list
    #
    # def visitEventDef(self, ctx):
    #     name = ctx.eventSymbol().getText().lower()
    #     params = self.visit(ctx.possibly_typed_variable_list())
    #     self.current_params = params
    #     try:
    #         precondition, effect = self.visit(ctx.actionDefBody())
    #     except UndeclaredVariable as error:
    #         raise SystemExit("Parsing event {}: undeclared variable {}".format(name, error))
    #     self.current_params = None
    #     evt = Event(name, params, len(params), precondition, effect)
    #     self.events.append(evt)
    #     # print( 'Action: {0}'.format(name) )
    #     # print( 'Parameters: {0}'.format(len(params)))
    #     # for parm in params :
    #     #    print(parm)
    #     # precondition.dump()
    #     # effect.dump()
    #
    # def visitConstraintDef(self, ctx):
    #     name = ctx.constraintSymbol().getText().lower()
    #     params = self.visit(ctx.possibly_typed_variable_list())
    #     self.current_params = params
    #
    #     try:
    #         conditions = self.visit(ctx.goalDesc())
    #     except UndeclaredVariable as error:
    #         raise SystemExit(
    #             "Parsing process {}: undeclared variable in {} found undeclared variable {}".
    #             format('state constraint', repr(error)))
    #
    #     self.current_params = None
    #     state_constraint = Constraint(name, params, conditions)
    #     self.constraint_schemata.append(state_constraint)


class UnresolvedVariableError(Exception):
    def __init__(self, value):
        self.value = value

    def __str__(self):
        return repr(self.value)


class UndeclaredVariable(Exception):
    def __init__(self, component, value):
        self.component = component
        self.value = value

    def __str__(self):
        return 'in {} found undeclared variable {}'.format(self.component, repr(self.value))


class ParserVariableContext:
    def __init__(self, parser: FStripsParser, pushed_variables, root=False):
        self.root = root
        self.parser = parser
        self.variables = pushed_variables
        self.previous_binding = None

    def __enter__(self):
        # Merge the new variable binding with the previous one, if it existed
        if self.root and self.parser.current_binding is not None:
            raise RuntimeError("Clean ParserVariableContext opened upon existing context")

        if self.parser.current_binding is None:
            self.parser.current_binding = VariableBinding(self.variables)
        else:
            self.previous_binding = copy.deepcopy(self.parser.current_binding)
            for v in self.variables:
                self.parser.current_binding.add(v)
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        # Restore the previous binding
        self.parser.current_binding = self.previous_binding


class ParsingError(SyntacticError):
    pass


class ExceptionRaiserListener(ErrorListener):
    """ An ANTLR ErrorListener that simply transforms any syntax error into a Tarski parsing error.
        Useful at least for testing purposes.
    """
    def syntaxError(self, recognizer, offending_symbol, line, column, msg, e):
        """ """
        msg = "line " + str(line) + ":" + str(column) + " " + msg
        raise ParsingError(msg)
