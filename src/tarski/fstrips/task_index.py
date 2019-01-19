# -*- coding: utf-8 -*-
"""
    Creates a TaskIndex for a  planning task as given by Tarski's AST.
"""
from .. import util
from .visitors import FluentSymbolCollector, FluentHeuristic


class TaskIndex:
    def __init__(self, domain_name, instance_name):
        self.domain_name = domain_name
        self.instance_name = instance_name
        self.all_symbols = util.UninitializedAttribute('all_symbols')
        self.static_symbols = util.UninitializedAttribute('static_symbols')
        self.fluent_symbols = util.UninitializedAttribute('fluent_symbols')
        self.static_terms = util.UninitializedAttribute('static_terms')
        self.fluent_terms = util.UninitializedAttribute('fluent_terms')
        self.initial_fluent_atoms = util.UninitializedAttribute('initial_fluent_atoms')
        self.initial_static_data = util.UninitializedAttribute('initial_static_data')
        self.state_variables = util.UninitializedAttribute('state_variables')

    def _check_static_not_fluents(self):
        """
            Sorts fluent and static sets, so that the only
            static expressions are those which haven't been flagged
            as fluent by at least one of our heuristics.
        """
        # print('Fluents (before filtering): {}'.format(','.join([str(var) for var in self.fluent_terms])))
        # print('Statics (before filtering): {}'.format(','.join([str(var) for var in self.static_terms])))
        self.static_terms = {x for x in self.static_terms if x not in self.fluent_terms}
        assert all([x not in self.static_terms for x in self.fluent_terms])
        # print('Fluents (after filtering): {}'.format(','.join([str(var) for var in self.fluent_terms])))
        # print('Statics (after filtering): {}'.format(','.join([str(var) for var in self.static_terms])))

    def process_symbols(self, problem):

        self.fluent_terms = set()
        self.static_terms = set()

        prec_visitor = FluentSymbolCollector(problem.language, self.fluent_terms, self.static_terms,
                                             FluentHeuristic.precondition)
        eff_visitor = FluentSymbolCollector(problem.language, self.fluent_terms, self.static_terms,
                                            FluentHeuristic.action_effects)
        constraint_visitor = FluentSymbolCollector(problem.language, self.fluent_terms, self.static_terms,
                                                   FluentHeuristic.constraint)

        o_f = len(self.fluent_terms)
        o_s = len(self.static_terms)
        while True:
            problem.get_symbols(prec_visitor, eff_visitor, constraint_visitor)

            # print('Fluents: {}'.format(','.join([str(x) for x in self.fluent_terms])))
            # print('Statics: {}'.format(','.join([str(x) for x in self.static_terms])))
            self._check_static_not_fluents()
            if len(self.fluent_terms) == o_f and len(self.static_terms) == o_s:
                break
            o_f = len(self.fluent_terms)
            o_s = len(self.static_terms)

        self.all_symbols = self.fluent_terms | self.static_terms

    def compute_fluent_and_statics(self):
        """ Return two sets of predicate symbols, one for fluent and one for statics """
        fluents = set(ref.phi.predicate for ref in self.fluent_terms)
        statics = set(ref.phi.predicate for ref in self.static_terms)
        return fluents, statics

    def is_fluent(self, symbol):
        return symbol in self.fluent_terms

    def process_initial_state(self, init):
        raise NotImplementedError()
