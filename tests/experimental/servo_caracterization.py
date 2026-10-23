#!/usr/bin/env python
# -*- coding: utf-8 -*-
# (C) 2020 David Toro <davsamirtor@gmail.com>
"""
MAPPING SETTING
steps -> delay  -> velocity
40    -> 03     -> 13.3
30    -> 04     -> 7.50
25    -> 06     -> 4.1
20    -> 10     -> 2
15    -> 15     -> 1
10    -> 20     -> 0.5
05    -> 30     -> 0.16
01    -> 30     -> 0.03

x = [(40, 3), (40, 4), (25, 6), (20, 10), (15, 15), (10, 20), (5, 30), (1, 30)]
y = [13.3,7.5, 4.1, 2, 1, 0.5, 0.16, 0.03]

get coefficients https://stackoverflow.com/a/43275321/5288758
                https://stackoverflow.com/a/34376993/5288758
polynomial https://scikit-learn.org/stable/auto_examples/linear_model/plot_polynomial_interpolation.html
code base https://scikit-learn.org/stable/auto_examples/linear_model/plot_ols_3d.html
"""

import matplotlib.pyplot as plt
import numpy as np
from mpl_toolkits.mplot3d import Axes3D

from sklearn import datasets, linear_model
from sklearn.linear_model import Ridge
from sklearn.preprocessing import PolynomialFeatures
from sklearn.pipeline import make_pipeline
import pandas as pd
from sympy import solve, Poly, Eq, Function, exp, Symbol, simplify, lambdify
from sympy.parsing.sympy_parser import parse_expr
from sympy.abc import x, y, z

A = "6.596117054967944 + 4.865825812559616*velocity + -0.1808491025328206*velocity**2 - steps"
B = "25.009254372746568 + -5.452902785819741*velocity + 0.2899634524263905*velocity**2 - delay"

A = "5.802971800941032 + 6.718145092581947*velocity + -0.630971144966802*velocity**2 + 0.023911720848915307*velocity**3 - steps"
B = "26.038352277156235 + -7.856268221962068*velocity + 0.8739922267846528*velocity**2 + -0.031025214727708333*velocity**3 - delay"

#A = "5.914487402606156 + 4.789087917414352*velocity + 0.7210398700581739*velocity**2 + -0.20026990114766657*velocity**3 + 0.010023172732688412*velocity**4 - steps"
#B = "25.915372885712863 + -5.728904212628325*velocity + -0.6170053499652562*velocity**2 + 0.2162022497190905*velocity**3 + -0.011053553624715188*velocity**4 - delay"
C = solve(Eq(parse_expr(A), parse_expr(B)), Symbol("velocity"))
#print(C[0].free_symbols)
#[i.evalf(subs={Symbol("steps"): 1, Symbol("delay"): 30}) for i in C]
# [({Symbol("steps"): step, Symbol("delay"): delay}, [i.evalf(subs={Symbol("steps"): step, Symbol("delay"): delay}) for i in C]) for step, delay in zip(steps, delays)]

steps = (40, 30, 25, 20, 15, 10, 5, 1)
delays = (3, 4, 6, 10, 15, 20, 30, 30)
#velocity = [13.3, 7.5, 4.1, 2, 1, 0.5, 0.16, 0.03]
velocity = [i/j for i, j in zip(steps, delays)]  # steps/delays
solve_for = {
    "steps": steps,
    "delay": delays,
    "velocity": velocity,
}

selected_output = "delay"

if selected_output == "velocity":
    # TODO, check if this can be used but it is unstable
    selected_input = ["steps", "delay"]
    x = [steps, delays]
    x = np.array(x).T
    y = np.array(solve_for[selected_output])
    # TODO, solve step and delay at the same time for velocity
    #selected_input = ["velocity"]
    #x = np.array(solve_for[selected_output]).reshape(-1, 1)
    #y = [steps, delays]
    #y = np.array(y).T
else:
    # step and delay are used individually feeding velocity and velocity must be gotten by solving these two
    selected_input = ["velocity"]
    x = np.array(velocity).reshape(-1, 1)
    y = np.array(solve_for[selected_output]).reshape(-1, 1)

X_train = np.array(x)
y_train = np.array(y)

degree = 3
ols = make_pipeline(PolynomialFeatures(degree), Ridge())
#ols = linear_model.LinearRegression()
ols.fit(X_train, y_train)
poly = ols["polynomialfeatures"]
columns = poly.get_feature_names(selected_input)

coefficients = ols.steps[1][1].coef_
intercept = ols.steps[1][1].intercept_
if coefficients.shape[0] == 1:
    coefficients = coefficients[0]
    intercept = intercept[0]

equation = f"{selected_output}={intercept} + "+" + ".join([f"{i}*{j.replace('^', '**').replace(' ', '*')}" for i, j in zip(coefficients, columns) if i])
iterations = pd.DataFrame(poly.transform(X_train), columns=columns)
print(f"equation: {equation}")
print(f"predicting {ols.predict(X_train)}")
print(f"of ground Truth {y_train}")
print(f"regression coefficients: {list(coefficients)}\nregression intercept: {intercept}")
print(f"iterations: \n{iterations}")


# #############################################################################
# Plot the figure
def plot_figs(fig_num, elev, azim, X_train, clf):
    fig = plt.figure(fig_num, figsize=(4, 3))
    plt.clf()
    ax = Axes3D(fig, elev=elev, azim=azim)

    try:
        second_ax = X_train[:, 1]
    except IndexError:
        second_ax = X_train[:, 0]

    ax.scatter(X_train[:, 0], second_ax, y_train, c='k', marker='+')
    ax.plot_surface(X_train[:, 0].reshape(2, 2, 2)[0], #np.array([[40, 40], [11, 1]]),
                    second_ax.reshape(2, 2, 2)[0], #np.array([[3, 4], [11, 30]]),
                    clf.predict(X_train#np.array([[40, 40, 11, 1], [3, 4, 11, 30]]).T
                                ).reshape((2, 2, 2))[0], alpha=.5)
    ax.set_xlabel('X_1')
    ax.set_ylabel('X_2')
    ax.set_zlabel('Y')
    ax.w_xaxis.set_ticklabels([])
    ax.w_yaxis.set_ticklabels([])
    ax.w_zaxis.set_ticklabels([])


# Generate the three different figures from different views
elev = 43.5
azim = -110
plot_figs(1, elev, azim, X_train, ols)

elev = -.5
azim = 0
plot_figs(2, elev, azim, X_train, ols)

elev = -.5
azim = 90
plot_figs(3, elev, azim, X_train, ols)

plt.show()

import heapq
def minPurchases(trip_durations, total_hours):
    min_purchases = -1

    # Put your code here to calculate min_purchases
    def apply_purchase(remaining, purchase_no=1):
        for trip_dur in trip_durations:
            remain = remaining - trip_dur
            if remain > 0:
                apply_purchase(remain, purchase_no + 1)
            elif remain == 0:
                heapq.heappush(heap, purchase_no)

    heap = []
    apply_purchase(total_hours, purchase_no=1)
    try:
        min_purchases = heapq.heappop(heap)
    except IndexError:
        pass

    # Return the result, do not change the structure
    return min_purchases