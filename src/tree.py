
import numpy as np
import networkx as nx
from scipy.sparse import csr_matrix
from scipy.sparse.csgraph import minimum_spanning_tree

def generateMST(twoPinList):
    # Two pin list: [[(0,0,0),(2,0,0)],[(2,0,0),(2,0,1)],[(2,0,1),(2,2,0)]]
    # Generate sorted two pin list based on tree approach

    # print('Original Two pin list: ', twoPinList)
    pinList = []
    for i in range(len(twoPinList)):
        pinList.append(twoPinList[i][0])
        pinList.append(twoPinList[i][1])

    pinList = list(set(pinList))
    # print(pinList)

    # Set Manhattan distance as weights of tree
    recDist = np.zeros((len(pinList),len(pinList)))
    for i in range(len(pinList)):
        for j in range(len(pinList)):
            recDist[i,j] = int(np.abs(pinList[i][0]-pinList[j][0])+ np.abs(pinList[i][1]-pinList[j][1])\
               +np.abs(pinList[i][2] - pinList[j][2]))

    X = csr_matrix(recDist)
    Tcsr = minimum_spanning_tree(X)
    Tree = Tcsr.toarray().astype(int)
    # print(Tree)

    twoPinListSorted = []
    for i in range(Tree.shape[0]):
        for j in range(Tree.shape[1]):
            if Tree[i,j] != 0:
                twoPinListSorted.append([pinList[i],pinList[j]])
#    print ('Sorted Two pin list: ',twoPinListSorted)
    return twoPinListSorted


def generateRMST(twoPinList):
    # Two pin list: [[(0,0,0),(2,0,0)],[(2,0,0),(2,0,1)],[(2,0,1),(2,2,0)]]
    # Generate sorted two pin list based on tree approach

    # Extract all pins from the twoPinList
    pinList = [item for sublist in twoPinList for item in sublist]
    # print(f"pinList before:{pinList}")
    pinList = list(set([item for sublist in twoPinList for item in sublist]))
    # print(f"pinList after:{pinList}")

    # Create a graph
    G = nx.Graph()

    # Add nodes and edges to the graph
    for i in range(len(pinList)):
        G.add_node(i, pos=pinList[i])

    # Add edges between all pairs of nodes
    for i in range(len(pinList)):
        for j in range(i + 1, len(pinList)):
            # Calculate the Manhattan distance as the edge weight
            weight = int(np.abs(pinList[i][0] - pinList[j][0]) + np.abs(pinList[i][1] - pinList[j][1]) + np.abs(pinList[i][2] - pinList[j][2]))
            G.add_edge(i, j, weight=weight)

    # Find the Steiner tree for the given set of terminals
    rmst = nx.algorithms.approximation.steiner_tree(G, list(range(len(pinList))))

    # Convert the Steiner tree to a list of edges
    rmst_edges = list(rmst.edges())

    # Convert the edges to the original pin format
    rmst_edges_formatted = [[pinList[edge[0]], pinList[edge[1]]] for edge in rmst_edges]
    # Filter out edges with identical start and end points before returning
    # rmst_edges_formatted = [edge for edge in rmst_edges_formatted if edge[0] != edge[1]]
    return rmst_edges_formatted

if __name__ == '__main__':

    # X = csr_matrix([[0, 8, 0, 3],
    #                 [0, 0, 2, 5],
    #                 [0, 0, 0, 6],
    #                 [0, 0, 0, 0]])
    #
    # Tcsr = minimum_spanning_tree(X)
    # print(Tcsr.toarray().astype(int))


    # Test Generate MST
    twoPinList = [[(0,0,0),(2,0,0)],[(2,0,0),(2,0,1)],[(2,0,1),(2,2,0)],[(2,2,0),(0,0,1)]]
    MST = generateMST(twoPinList)
