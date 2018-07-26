"""
    Generate simple numeric domain language elements
"""
import tarski as tsk
from tarski.theories import Theory


def generate_numeric_instance():
    lang = tsk.fstrips.language(theories=[Theory.EQUALITY, Theory.ARITHMETIC])

    # The sorts
    particle = lang.sort('particle')

    x = lang.function('x', particle, lang.Real)
    y = lang.function('y', particle, lang.Real)
    f = lang.function('f', particle, lang.Real)

    # Particles
    for k in (1, 2, 3, 4):
        lang.constant('p{}'.format(k), particle)

    return lang

def generate_billiards_instance():

    lang = tsk.fstrips.language(theories=[Theory.EQUALITY, Theory.ARITHMETIC])

    # The sorts
    ball = lang.sort('ball')
    dim = lang.sort('dimension')
    force = lang.sort('force')

    # The stuff
    lang.balls = []
    for k in (1,2):
        bk = lang.constant('ball_{}'.format(k), ball)
        lang.balls.append(bk)

    lang.dimensions = []
    for d in ('x','y'):
        dk = lang.constant(d, dim)
        lang.dimensions.append(dk)

    lang.forces = []
    for n in ('cue', 'friction', 'resistance'):
        fk = lang.constant(n, force)
        lang.forces.append(fk)

    # The properties of stuff
    m = lang.function('m', ball, lang.Real)
    F = lang.function('F', force, dim, ball, lang.Real)
    a = lang.function('a', dim, ball, lang.Real)
    v = lang.function('v', dim, ball, lang.Real)
    p = lang.function('p', dim, ball, lang.Real)

    return lang
