
from tarski.grounding import ProblemGrounding, create_all_possible_state_variables
from tarski.grounding.naive import instantiation
from tarski.syntax import create_substitution
from tarski.util import IndexDictionary
from tarski.grounding.naive.actions import ActionGrounder
from tarski.grounding.naive.sensors import SensorGrounder
from tarski.grounding.naive.constraints import ConstraintGrounder
from tarski.grounding.naive.diff_constraints import DifferentialConstraintGrounder
from tarski.grounding.naive.reactions import ReactionGrounder

from ..common.blocksworld import create_4blocks_task
from ..fstrips.contingent import localize
from ..fstrips.hybrid.tasks import create_particles_world, create_billiards_world


def create_small_bw_with_index():
    problem = create_4blocks_task()
    grounding = ProblemGrounding(problem)
    grounding.process_symbols(problem)
    grounding.state_variables = IndexDictionary()

    for var in create_all_possible_state_variables(grounding.fluent_terms):
        grounding.state_variables.add(var)

    return problem, grounding


def test_enumeration_of_action_parameters_for_small_bw():
    prob, index = create_small_bw_with_index()
    index.ground_actions = IndexDictionary()
    actions = list(prob.actions.values())
    card, syms, substs = instantiation.enumerate_groundings(actions[0].parameters)
    assert card == 6
    assert len(syms) == 1
    assert len(substs) == 1


def test_generate_substitutions_for_small_bw():
    import itertools

    prob, index = create_small_bw_with_index()
    index.ground_actions = IndexDictionary()
    actions = list(prob.actions.values())
    card, syms, substs = instantiation.enumerate_groundings(actions[0].parameters)
    for values in itertools.product(*substs):
        assert (len(syms) == len(values))
        subst = create_substitution(syms, values)
        assert len(subst) == 1


def test_ground_actions_for_small_bw():
    # import itertools, copy

    prob, index = create_small_bw_with_index()
    grounder = ActionGrounder(prob, index)
    grounder.calculate_actions()
    assert len(prob.ground_actions) == 84


def test_ground_constraints_for_small_bw():
    prob, index = create_small_bw_with_index()
    grounder = ConstraintGrounder(prob, index)
    grounder.calculate_constraints()
    assert len(prob.ground_constraints) == 0


def test_ground_sensors_for_small_contingent_problem():
    prob = localize.create_small_task()
    index = ProblemGrounding(prob)
    index.process_symbols(prob)
    index.state_variables = IndexDictionary()

    grounder = SensorGrounder(prob, index)
    grounder.calculate_sensors()
    assert len(prob.ground_sensors) == 4


def test_ground_differential_constraints_for_hybrid_problem():
    prob = create_particles_world()
    index = ProblemGrounding(prob)
    index.process_symbols(prob)
    index.state_variables = IndexDictionary()
    grounder = DifferentialConstraintGrounder(prob, index)
    grounder.calculate_constraints()
    assert len(prob.ground_differential_constraints) == 8


def test_ground_reactions_for_hybrid_problem():
    prob = create_billiards_world()
    index = ProblemGrounding(prob)
    index.process_symbols(prob)
    index.state_variables = IndexDictionary()
    grounder = ReactionGrounder(prob, index)
    grounder.calculate_reactions()
    assert len(prob.ground_reactions) == 4
