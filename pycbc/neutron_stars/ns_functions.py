# Copyright (C) 2015 Francesco Pannarale
#
# This program is free software; you can redistribute it and/or modify it
# under the terms of the GNU General Public License as published by the
# Free Software Foundation; either version 3 of the License, or (at your
# option) any later version.
#
# This program is distributed in the hope that it will be useful, but
# WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the GNU General
# Public License for more details.
#
# You should have received a copy of the GNU General Public License along
# with this program; if not, write to the Free Software Foundation, Inc.,
# 51 Franklin Street, Fifth Floor, Boston, MA  02110-1301, USA.

import os.path
import sys
import logging
import numpy as np
from scipy.optimize import fsolve
from scipy.interpolate import interp1d
from . import NS_SEQUENCES, NS_SEQUENCE_FILE_DIRECTORY

##############################################################################
# Innermost Stable Spherical Orbit (ISSO) solver in the Perez-Giz (PG)       #
# formalism [see Stone, Loeb, Berger, PRD 87, 084053 (2013)].                #
##############################################################################

# Equation that determines the ISCO radius (in BH mass units)
def ISCO_eq(r, chi):
    """
    Polynomial that enables the calculation of the Kerr
    inntermost stable circular orbit (ISCO) radius via its
    roots.

    Parameters
    -----------
    r: float
        the radial coordinate in BH mass units
    chi: float
        the BH dimensionless spin parameter

    Returns
    ----------
    float
        (r*(r-6))**2-chi**2*(2*r*(3*r+14)-9*chi**2)
    """
    return (r*(r-6))**2-chi**2*(2*r*(3*r+14)-9*chi**2)

# Equation that determines the ISSO radius (in BH mass units) at one of the
# poles
def ISSO_eq_at_pole(r, chi):
    """
    Polynomial that enables the calculation of the Kerr polar
    (inclination = +/- pi/2) innermost stable spherical orbit
    (ISSO) radius via its roots.  Physical solutions are
    between 6 and 1+sqrt[3]+sqrt[3+2sqrt[3]].

    Parameters
    ----------
    r: float
        the radial coordinate in BH mass units
    chi: float
        the BH dimensionless spin parameter

    Returns
    -------
    float
        r**3*(r**2*(r-6)+chi**2*(3*r+4))+chi**4*(3*r*(r-2)+chi**2)
    """
    return r**3*(r**2*(r-6)+chi**2*(3*r+4))+chi**4*(3*r*(r-2)+chi**2)

# Equation that determines the ISSO radius (in BH mass units) for a generic
# orbital inclination
def PG_ISSO_eq(r, chi, incl):
    """Polynomial that enables the calculation of a generic innermost
    stable spherical orbit (ISSO) radius via its roots.  Physical
    solutions are between the equatorial ISSO (aka the ISCO) radius
    and the polar ISSO radius. See Stone, Loeb, Berger, PRD 87, 084053 (2013).

    Parameters
    ----------
    r: float
        the radial coordinate in BH mass units
    chi: float
        the BH dimensionless spin parameter
    incl: float
        inclination angle between the BH spin and the orbital angular
        momentum in radians

    Returns
    -------
    float
        ``r**8*Z+chi**2*(1-cos_incl**2)*(chi**2*(1-cos_incl**2)*Y-2*r**4*X)``
        where
        ``X=chi**2*(chi**2*(3*chi**2+4*r*(2*r-3))+r**2*(15*r*(r-4)+28))-6*r**4*(r**2-4)``
        ``Y=chi**4*(chi**4+r**2*(7*r*(3*r-4)+36))+6*r*(r-2)*(chi**6+2*r**3*(chi**2*(3*r+2)+3*r**2*(r-2)))``
        ``Z=ISCO_eq(r,chi)``
    """
    chi2 = chi*chi
    chi4 = chi2*chi2
    r2 = r*r
    r4 = r2*r2
    three_r = 3*r
    r_minus_2 = r - 2
    sin_incl2 = (np.sin(incl))**2

    X = chi2*(chi2*(3*chi2+4*r*(2*r-3))+r2*(15*r*(r-4)+28))-6*r4*(r2-4)
    Y = chi4 * (chi4+r2*(7 * r * (three_r-4)+36))+6 * r * r_minus_2 * \
        (chi4*chi2+2*r2*r*(chi2*(three_r+2)+3*r2*r_minus_2))
    Z = ISCO_eq(r, chi)

    return r4*r4*Z+chi2*sin_incl2*(chi2*sin_incl2*Y-2*r4*X)

# ISSO radius solver
def PG_ISSO_solver(chi,incl):
    """Function that determines the radius of the innermost stable
    spherical orbit (ISSO) for a Kerr BH and a generic inclination
    angle between the BH spin and the orbital angular momentum.
    This function finds the appropriat root of PG_ISSO_eq.

    Parameters
    ----------
    chi: float
        the BH dimensionless spin parameter
    incl: float
        the inclination angle between the BH spin and the orbital
        angular momentum in radians

    Returns
    -------
    solution: float
        the radius of the orbit in BH mass units
    """
    # Auxiliary variables
    cos_incl = np.cos(incl)
    sgnchi = np.sign(cos_incl)*chi

    # ISCO radius for the given spin magnitude
    initial_guess = [2 if s > 0.99 else (9 if s < 0 else 5) for s in sgnchi]
    rISCO_limit = np.array([
        fsolve(ISCO_eq, g0, args=sc)[0]
        for g0, sc in zip(initial_guess, sgnchi)])
    # If the inclination is 0 or pi, just output the ISCO radius
    equatorial = (incl == 0) | (incl == np.pi)
    if all(equatorial):
        return rISCO_limit

    # ISSO radius for an inclination of pi/2
    initial_guess = [9 if c < 0 else 6 for c in chi]
    rISSO_at_pole_limit = np.array([
        fsolve(ISSO_eq_at_pole, g0, args=c)[0]
        for g0, c in zip(initial_guess, chi)])
    # If the inclination is pi/2, just output the ISSO radius at the pole(s)
    polar = (incl == np.pi/2)
    if all(polar):
        return rISSO_at_pole_limit

    # Otherwise, find the ISSO radius for a generic inclination
    initial_guess = np.maximum(rISCO_limit, rISSO_at_pole_limit)
    solution = np.array([
        fsolve(PG_ISSO_eq, g0, args=(c, inc))[0]
        for g0, c, inc in zip(initial_guess, chi, incl)])
    oob = (solution < 1) | (solution > 9)
    n = 1
    while any(oob):
        if n > 5:
            raise RuntimeError('Unable to obtain some solutions!')
        initial_guess = np.minimum(rISCO_limit, rISSO_at_pole_limit)
        solution = np.array([
            fsolve(PG_ISSO_eq, g0, args=(c, inc))[0] if ob else sol
            for g0, c, inc, ob, sol
            in zip(initial_guess, chi, incl, oob, solution)])
        oob = (solution < 1) | (solution > 9)
        n += 1
    return solution


##############################################################################
# 2H 2-piecewise polytropic EOS, NS non-rotating equilibrium sequence        #
# File format is: grav mass (Msun)   baryonic mass (Msun)    compactness     #
#                                                                            #
# Eventually, the function should call an NS sequence generator within LAL   #
# the EOS prescribed by the user and store it.                               #
##############################################################################
def load_ns_sequence(eos_name):
    """
    Load the data of an NS non-rotating equilibrium sequence
    generated using the equation of state (EOS) chosen by the
    user.  [Only the 2H 2-piecewise polytropic EOS is currently
    supported.  This yields NSs with large radiss (15-16km).]

    Parameters
    -----------
    eos_name: string
        NS equation of state label ('2H' is the only supported
        choice at the moment)

    Returns
    ----------
    ns_sequence: 3D-array
        contains the sequence data in the form NS gravitational
         mass (in solar masses), NS baryonic mass (in solar
         masses), NS compactness (dimensionless)
    max_ns_g_mass: float
        the maximum NS gravitational mass (in solar masses) in
        the sequence (this is the mass of the most massive stable
        NS)
    """
    if eos_name not in NS_SEQUENCES:
        raise NotImplementedError(
            f'{eos_name} does not have an implemented NS sequence file! '
            f'To implement, the file {ns_sequence_file} must exist and '
            'contain: NS gravitational mass (in solar masses), NS baryonic '
            'mass (in solar masses), NS compactness (dimensionless)')
    ns_sequence_file = os.path.join(
        NS_SEQUENCE_FILE_DIRECTORY, 'equil_{}.dat'.format(eos_name))
    ns_sequence = np.loadtxt(ns_sequence_file)
    max_ns_g_mass = max(ns_sequence[:,0])
    return (ns_sequence, max_ns_g_mass)


##############################################################################
# Given an NS equilibrium sequence and gravitational mass (in Msun), return  #
# the NS baryonic mass (in Msun).                                            #
##############################################################################
def ns_g_mass_to_ns_b_mass(ns_g_mass, ns_sequence):
    """
    Determines the baryonic mass of an NS given its gravitational
    mass and an NS equilibrium sequence.

    Parameters
    -----------
    ns_g_mass: float
        NS gravitational mass (in solar masses)
    ns_sequence: 3D-array
        contains the sequence data in the form NS gravitational
         mass (in solar masses), NS baryonic mass (in solar
         masses), NS compactness (dimensionless)

    Returns
    ----------
    float
        The NS baryonic mass (in solar massesr**3*(r**2*(r-6)+chi**2*(3*r+4))+
        chi**4*(3*r*(r-2)+chi**2))
    """
    x = ns_sequence[:,0]
    y = ns_sequence[:,1]
    f = interp1d(x, y)

    return f(ns_g_mass)

##############################################################################
# Given an NS equilibrium sequence and gravitational mass (in Msun), return  #
# the NS compactness.                                                        #
##############################################################################
def ns_g_mass_to_ns_compactness(ns_g_mass, ns_sequence):
    """
    Determines the compactness of an NS given its
    gravitational mass and an NS equilibrium sequence.

    Parameters
    -----------
    ns_g_mass: float
        NS gravitational mass (in solar masses)
    ns_sequence: 3D-array
        contains the sequence data in the form NS gravitational
         mass (in solar masses), NS baryonic mass (in solar
         masses), NS compactness (dimensionless)

    Returns
    ----------
    float
        The NS compactness (dimensionless)
    """
    x = ns_sequence[:,0]
    y = ns_sequence[:,2]
    f = interp1d(x, y)

    return f(ns_g_mass)
