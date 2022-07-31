import sys

if (len(sys.argv) != 1):
    print("usage: python train.py")
    exit()

from q_learn import q_learning
q_learning("train")