from sklearn.preprocessing import StandardScaler
import pandas as pd

df = pd.DataFrame({
    "age": [20, 30, 40],
    "salary": [2000, 3000, 4000]
})

scaler = StandardScaler()

scaled = scaler.fit_transform(df)
print(scaled)