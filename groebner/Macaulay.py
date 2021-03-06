from operator import itemgetter
import itertools
import numpy as np
from groebner import maxheap
import math
from groebner.multi_cheb import MultiCheb
from groebner.multi_power import MultiPower
from scipy.linalg import lu, qr, solve_triangular
from groebner.maxheap import Term
import matplotlib.pyplot as plt
import time
from collections import defaultdict

#What we determine to be zero throughout the code
global_accuracy = 1.e-12
#If clean is true then at a couple of places (end of rrqr_reduce and end of add r to matrix) things close to 0 will be made 0.
#Might make it more stable, might make it less stable. Not sure.
clean = True

def Macaulay(initial_poly_list, global_accuracy = 1.e-10):
    """
    Macaulay will take a list of polynomials and use them to construct a Macaulay matrix.

    parameters
    --------
    initial_poly_list: A list of polynomials
    global_accuracy: How small we want a number to be before assuming it is zero.
    --------

    Returns
    -----------
    Reduced Macaulay matrix that can be passed into the root finder.
    -----------
    """

    Power = bool
    if all([type(p) == MultiPower for p in initial_poly_list]):
        Power = True
    elif all([type(p) == MultiCheb for p in initial_poly_list]):
        Power = False
    else:
        print([type(p) == MultiPower for p in initial_poly_list])
        raise ValueError('Bad polynomials in list')

    poly_list = []
    degree = find_degree(initial_poly_list)
    for i in initial_poly_list:
        poly_list = add_polys(degree, i, poly_list)
    matrix, matrix_terms = create_matrix(poly_list)
    matrix = rrqr_reduce(matrix)
    rows = get_good_rows(matrix, matrix_terms)
    final_polys = get_poly_from_matrix(rows,matrix,matrix_terms,Power)
    return final_polys

def get_poly_from_matrix(rows,matrix,matrix_terms,power):
    '''
    Takes a list of indicies corresponding to the rows of the reduced matrix and
    returns a list of polynomial objects
    '''
    shape = []
    p_list = []
    matrix_term_vals = [i.val for i in matrix_terms]

    # Finds the maximum size needed for each of the poly coeff tensors
    for i in range(len(matrix_term_vals[0])):
        # add 1 to each to compensate for constant term
        shape.append(max(matrix_term_vals, key=itemgetter(i))[i]+1)
    # Grabs each polynomial, makes coeff matrix and constructs object
    for i in rows:
        p = matrix[i]
        coeff = np.zeros(shape)
        for j,term in enumerate(matrix_term_vals):
            coeff[term] = p[j]

        if power:
            poly = MultiPower(coeff)
        else:
            poly = MultiCheb(coeff)

        if poly.lead_term != None:
            p_list.append(poly)
    return p_list

def divides(a,b):
    '''
    Takes two terms, a and b. Returns True if b divides a. False otherwise.
    '''
    diff = tuple(i-j for i,j in zip(a.val,b.val))
    return all(i >= 0 for i in diff)

def get_good_rows(matrix, matrix_terms):
    '''
    Gets the rows in a matrix whose leading monomial is not divisible by the leading monomial of any other row.
    Returns a list of rows.
    This function could probably be improved, but for now it is good enough.
    '''
    rowLMs = dict()
    already_looked_at = set()
    #Finds the leading terms of each row.
    for i, j in zip(*np.where(matrix!=0)):
        if i in already_looked_at:
            continue
        else:
            already_looked_at.add(i)
            rowLMs[i] = matrix_terms[j]
    keys= list(rowLMs.keys())
    keys = keys[::-1]
    spot = 0
    #Uses a sieve to find which of the rows to keep.
    while spot != len(keys):
        term1 = rowLMs[keys[spot]]
        toRemove = list()
        for i in range(spot+1, len(keys)):
            term2 = rowLMs[keys[i]]
            if divides(term2,term1):
                toRemove.append(keys[i])
        for i in toRemove:
            keys.remove(i)
        spot += 1
    return keys

def find_degree(poly_list):
    """
    Takes a list of polynomials and finds the degree needed for a Macaulay matrix.
    Adds the degree of each polynomial and then subtracts the total number of polynomials and adds one.

    Example:
        For polynomials [P1,P2,P3] with degree [d1,d2,d3] the function returns d1+d2+d3-3+1

    """
    degree_needed = 0
    for poly in poly_list:
        degree_needed += poly.degree
    return ((degree_needed - len(poly_list)) + 1)

def mon_combos(mon, numLeft, spot = 0):
    '''
    This function finds all the monomials up to a given degree (here numLeft) and returns them.
    mon is a tuple that starts as all 0's and gets changed as needed to get all the monomials.
    numLeft starts as the dimension, but as the code goes is how much can still be added to mon.
    spot is the place in mon we are currently adding things too.
    Returns a list of all the possible monomials.
    '''
    answers = list()
    if len(mon) == spot+1: #We are at the end of mon, no more recursion.
        for i in range(numLeft+1):
            mon[spot] = i
            answers.append(mon.copy())
        return answers
    if numLeft == 0: #Nothing else can be added.
        answers.append(mon.copy())
        return answers
    temp = mon.copy() #Quicker than copying every time inside the loop.
    for i in range(numLeft+1): #Recursively add to mon further down.
        temp[spot] = i
        answers += mon_combos(temp, numLeft-i, spot+1)
    return answers

def add_polys(degree, poly, poly_list):
    """
    Take each polynomial and adds it to a poly_list
    Then uses monomial multiplication and adds all polynomials with degree less than
        or equal to the total degree needed.
    Returns a list of polynomials.
    """
    poly_list.append(poly)
    deg = degree - poly.degree
    dim = poly.dim
    mons = mon_combos(np.zeros(dim),deg)
    mons = mons[1:]
    for i in mons:
        poly_list.append(poly.mon_mult(i))
    return poly_list

def row_swap_matrix(matrix):
    '''
    Rearange the rows of the matrix so it starts close to upper traingular and return it.
    '''
    rows, columns = np.where(matrix != 0)
    lms = {}
    last_i = -1
    lms = list()
    #Finds the leading column of each row and adds it to lms.
    for i,j in zip(rows,columns):
        if i == last_i:
            continue
        else:
            lms.append(j)
            last_i = i
    #Get the list by which we sort the matrix, first leading columns first.
    argsort_list = sorted(range(len(lms)), key=lms.__getitem__)[::]
    return matrix[argsort_list]

def fill_size(bigShape,smallPolyCoeff):
    '''
    Pads the smallPolyCoeff so it has the same shape as bigShape. Does this by making a matrix with the shape of
    bigShape and then dropping smallPolyCoeff into the top of it with slicing.
    Returns the padded smallPolyCoeff.
    '''
    if (smallPolyCoeff.shape == bigShape).all():
        return smallPolyCoeff
    matrix = np.zeros(bigShape)

    slices = list()
    for i in smallPolyCoeff.shape:
        s = slice(0,i)
        slices.append(s)
    matrix[slices] = smallPolyCoeff
    return matrix

def sort_matrix(matrix, matrix_terms):
    '''
    Takes a matrix and matrix_terms (holding the terms in each column of the matrix), and sorts them both
    by term order.
    Returns the sorted matrix and matrix_terms.
    '''
    #argsort_list gives the ordering by which the matrix should be sorted.
    argsort_list = sorted(range(len(matrix_terms)), key=matrix_terms.__getitem__)[::-1]
    matrix_terms.sort()
    matrix = matrix[:,argsort_list]
    return matrix, matrix_terms[::-1]

def clean_matrix(matrix, matrix_terms):
    '''
    Gets rid of columns in the matrix that are all zero and returns it and the updated matrix_terms.
    '''
    non_zero_monomial = np.sum(abs(matrix), axis=0) != 0
    matrix = matrix[:,non_zero_monomial] #Only keeps the non_zero_monomials
    matrix_terms = matrix_terms[non_zero_monomial] #Only keeps the non_zero_monomials
    return matrix, matrix_terms

def create_matrix(polys):
    '''
    Takes a list of polynomial objects (polys) and uses them to create a matrix. That is ordered by the monomial
    ordering. Returns the matrix and the matrix_terms, a list of the monomials corresponding to the rows of the matrix.
    '''
    #Gets an empty polynomial whose lm all other polynomial divide into.
    bigShape = np.maximum.reduce([p.coeff.shape for p in polys])

    #Gets a list of all the flattened polynomials.
    flat_polys = list()
    for poly in polys:
        #Gets a matrix that is padded so it is the same size as biggest, and flattens it. This is so
        #all flattened polynomials look the same.
        newMatrix = fill_size(bigShape, poly.coeff)
        flat_polys.append(newMatrix.ravel())

    #Make the matrix
    matrix = np.vstack(flat_polys[::-1])

    #Makes matrix_terms, a list of all the terms in the matrix.
    terms = np.zeros(bigShape, dtype = Term)
    for i,j in np.ndenumerate(terms):
        terms[i] = Term(i)
    matrix_terms = terms.ravel()

    #Sorts the matrix and matrix_terms by term order.
    matrix, matrix_terms = sort_matrix(matrix, matrix_terms)

    #Gets rid of any columns that are all 0.
    matrix, matrix_terms = clean_matrix(matrix, matrix_terms)

    #Sorts the rows of the matrix so it is close to upper triangular.
    matrix = row_swap_matrix(matrix)

    return matrix, matrix_terms

def rrqr_reduce(matrix, global_accuracy = 1.e-10):
    '''
    Recursively reduces the matrix using rrqr reduction so it returns a reduced matrix, where each row has
    a unique leading monomial.
    '''
    if matrix.shape[0]==0 or matrix.shape[1]==0:
        return matrix
    height = matrix.shape[0]
    A = matrix[:height,:height] #Get the square submatrix
    B = matrix[:,height:] #The rest of the matrix to the right
    Q,R,P = qr(A, pivoting = True) #rrqr reduce it
    PT = inverse_P(P)
    diagonals = np.diagonal(R) #Go along the diagonals to find the rank
    rank = np.sum(np.abs(diagonals)>global_accuracy)

    if rank == height: #full rank, do qr on it
        Q,R = qr(A)
        A = R #qr reduce A
        B = Q.T.dot(B) #Transform B the same way
    else: #not full rank
        A = R[:,PT] #Switch the columns back
        B = Q.T.dot(B) #Multiply B by Q transpose
        #sub1 is the top part of the matrix, we will recursively reduce this
        #sub2 is the bottom part of A, we will set this all to 0
        #sub3 is the bottom part of B, we will recursively reduce this.
        #All submatrices are then put back in the matrix and it is returned.
        sub1 = np.hstack((A[:rank,],B[:rank,])) #Takes the top parts of A and B
        result = rrqr_reduce(sub1) #Reduces it
        A[:rank,] = result[:,:height] #Puts the A part back in A
        B[:rank,] = result[:,height:] #And the B part back in B

        sub2 = A[rank:,]
        zeros = np.zeros_like(sub2)
        A[rank:,] = np.zeros_like(sub2)

        sub3 = B[rank:,]
        B[rank:,] = rrqr_reduce(sub3)

    reduced_matrix = np.hstack((A,B))
    non_zero_rows = np.sum(abs(reduced_matrix),axis=1) != 0
    reduced_matrix = reduced_matrix[non_zero_rows,:] #Only keeps the non_zero_polymonials
    return reduced_matrix

def inverse_P(p):
    P = np.eye(len(p))[:,p]
    return np.where(P==1)[1]
