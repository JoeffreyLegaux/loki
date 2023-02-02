# (C) Copyright 2018- ECMWF.
# This software is licensed under the terms of the Apache Licence Version 2.0
# which can be obtained at http://www.apache.org/licenses/LICENSE-2.0.
# In applying this licence, ECMWF does not waive the privileges and immunities
# granted to it by virtue of its status as an intergovernmental organisation
# nor does it submit to any jurisdiction.

from pathlib import Path
import pytest
import numpy as np

from conftest import jit_compile, clean_test, available_frontends
from loki import Subroutine
from loki.expression import symbols as sym
from loki.transform import promote_variables, normalize_range_indexing, flatten_arrays
from loki import fgen

@pytest.fixture(scope='module', name='here')
def fixture_here():
    return Path(__file__).parent


@pytest.mark.parametrize('frontend', available_frontends())
def test_transform_promote_variable_scalar(here, frontend):
    """
    Apply variable promotion for a single scalar variable.
    """
    fcode = """
subroutine transform_promote_variable_scalar(ret)
  implicit none
  integer, intent(out) :: ret
  integer :: tmp, jk

  ret = 0
  do jk=1,10
    tmp = jk
    ret = ret + tmp
  end do
end subroutine transform_promote_variable_scalar
    """.strip()
    routine = Subroutine.from_source(fcode, frontend=frontend)

    # Test the original implementation
    filepath = here/(f'{routine.name}_{frontend}.f90')
    function = jit_compile(routine, filepath=filepath, objname=routine.name)
    ret = function()
    assert ret == 55

    # Apply and test the transformation
    assert isinstance(routine.variable_map['tmp'], sym.Scalar)
    promote_variables(routine, ['TMP'], pos=0, index=routine.variable_map['JK'], size=sym.Literal(10))
    assert isinstance(routine.variable_map['tmp'], sym.Array)
    assert routine.variable_map['tmp'].shape == (sym.Literal(10),)

    promoted_filepath = here/(f'{routine.name}_promoted_{frontend}.f90')
    promoted_function = jit_compile(routine, filepath=promoted_filepath, objname=routine.name)
    ret = promoted_function()
    assert ret == 55

    clean_test(filepath)
    clean_test(promoted_filepath)


@pytest.mark.parametrize('frontend', available_frontends())
def test_transform_promote_variables(here, frontend):
    """
    Apply variable promotion for scalar and array variables.
    """
    fcode = """
subroutine transform_promote_variables(scalar, vector, n)
  implicit none
  integer, intent(in) :: n
  integer, intent(inout) :: scalar, vector(n)
  integer :: tmp_scalar, tmp_vector(n), tmp_matrix(n,n)
  integer :: jl, jk

  do jl=1,n
    ! a bit of a hack to create initialized meaningful output
    tmp_vector(:) = 0
  end do

  do jl=1,n
    tmp_scalar = jl
    tmp_vector(jl) = jl

    do jk=1,n
      tmp_matrix(jk, jl) = jl + jk
    end do
  end do

  scalar = 0
  do jl=1,n
    scalar = scalar + tmp_scalar
    vector = tmp_matrix(:,jl) + tmp_vector(:)
  end do
end subroutine transform_promote_variables
    """.strip()
    routine = Subroutine.from_source(fcode, frontend=frontend)
    normalize_range_indexing(routine) # Fix OMNI nonsense

    # Test the original implementation
    filepath = here/(f'{routine.name}_{frontend}.f90')
    function = jit_compile(routine, filepath=filepath, objname=routine.name)

    n = 10
    scalar = np.zeros(shape=(1,), order='F', dtype=np.int32)
    vector = np.zeros(shape=(n,), order='F', dtype=np.int32)
    function(scalar, vector, n)
    assert scalar == n*n
    assert np.all(vector == np.array(list(range(1, 2*n+1, 2)), order='F', dtype=np.int32) + n + 1)

    # Verify dimensions before promotion
    assert isinstance(routine.variable_map['tmp_scalar'], sym.Scalar)
    assert isinstance(routine.variable_map['tmp_vector'], sym.Array)
    assert routine.variable_map['tmp_vector'].shape == (routine.variable_map['n'],)
    assert isinstance(routine.variable_map['tmp_matrix'], sym.Array)
    assert routine.variable_map['tmp_matrix'].shape == (routine.variable_map['n'], routine.variable_map['n'])

    # Promote scalar and vector and verify dimensions
    promote_variables(routine, ['tmp_scalar', 'tmp_vector'], pos=-1, index=routine.variable_map['JL'],
                      size=routine.variable_map['n'])

    assert isinstance(routine.variable_map['tmp_scalar'], sym.Array)
    assert routine.variable_map['tmp_scalar'].shape == (routine.variable_map['n'],)
    assert isinstance(routine.variable_map['tmp_vector'], sym.Array)
    assert routine.variable_map['tmp_vector'].shape == (routine.variable_map['n'], routine.variable_map['n'])
    assert isinstance(routine.variable_map['tmp_matrix'], sym.Array)
    assert routine.variable_map['tmp_matrix'].shape == (routine.variable_map['n'], routine.variable_map['n'])

    # Promote matrix and verify dimensions
    promote_variables(routine, ['tmp_matrix'], pos=1, index=routine.variable_map['JL'],
                      size=routine.variable_map['n'])

    assert isinstance(routine.variable_map['tmp_scalar'], sym.Array)
    assert routine.variable_map['tmp_scalar'].shape == (routine.variable_map['n'],)
    assert isinstance(routine.variable_map['tmp_vector'], sym.Array)
    assert routine.variable_map['tmp_vector'].shape == (routine.variable_map['n'], routine.variable_map['n'])
    assert isinstance(routine.variable_map['tmp_matrix'], sym.Array)
    assert routine.variable_map['tmp_matrix'].shape == (routine.variable_map['n'], ) * 3

    # Test promoted routine
    promoted_filepath = here/(f'{routine.name}_promoted_{frontend}.f90')
    promoted_function = jit_compile(routine, filepath=promoted_filepath, objname=routine.name)

    scalar = np.zeros(shape=(1,), order='F', dtype=np.int32)
    vector = np.zeros(shape=(n,), order='F', dtype=np.int32)
    promoted_function(scalar, vector, n)
    assert scalar == n*(n+1)//2
    assert np.all(vector[:-1] == np.array(list(range(n + 1, 2*n)), order='F', dtype=np.int32))
    assert vector[-1] == 3*n

    clean_test(filepath)
    clean_test(promoted_filepath)


@pytest.mark.parametrize('frontend', available_frontends())
def test_transform_flatten_arrays(here, frontend):
    """
    ...
    """

    fcode = """
    subroutine kernel(x1, x2, x3, x4)
        integer :: i1, i2, i3, i4, i5
        integer, parameter :: l1 = 10
        integer, parameter :: l2 = 20
        integer, parameter :: l3 = 30
        integer, parameter :: l4 = 40
        real :: x1(l1), x2(l2, l1), x3(l3, l2, l1), x4(l4, l3, l2, l1)
        
        do i1=1,l1
            x1(i1) = 1.0
            do i2=1,l2
                x2(i2, i1) = 2.0
                do i3=1,l3
                    x3(i3, i2, i1) = 3.0
                    do i4=1,l4
                        x4(i4, i3, i2, i1) = 4.0
                    end do
                end do
            end do
        end do
        
        
    end subroutine kernel
    """

    print("")
    print("Fortran style ...")
    routine = Subroutine.from_source(fcode, frontend=frontend)
    flatten_arrays(routine=routine, order='F', start_index=1)
    print(fgen(routine))

    print("")
    print("C style ...")
    routine = Subroutine.from_source(fcode, frontend=frontend)
    flatten_arrays(routine=routine, order='C', start_index=0)
    print(fgen(routine))

