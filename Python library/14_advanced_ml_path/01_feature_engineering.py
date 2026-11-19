import pandas as pd

df = pd.DataFrame({
    "age": [20, 30, 40],
    "salary": [2000, 3000, 4000]
})

# Create new feature
df["age_squared"] = df["age"] ** 2

# Binning
df["age_group"] = pd.cut(df["age"], bins=[0,25,35,50], labels=["young","mid","senior"])

# Encoding
df = pd.get_dummies(df, columns=["age_group"])

print(df)