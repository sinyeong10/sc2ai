### 아래의 2값을 고민
1. (3.465069005204695, [1, 2, 2, 2, 3, 3, 3, 3, 1, 3, 9], 159, 725)
2. (3.533597285133416, [1, 2, 2, 2, 0, 3, 3, 3, 3, 3, 9], 164, 726)
# 1이 더 효율적이지만 2가 더 보상이 큼

<br>

 [0, 0, 0, 0]
0 (0.019897808043493576, [0, 1, 2, 2, 2, 3, 3, 3, 3, 1, 3, 9], 1, 733)
1 (1.002472793958591, [1, 2, 2, 2, 3, 3, 3, 3, 1, 3, 9], 46, 725)     
2, 0, (12, 15, 12, 1, 2, 1, 0)가 없음
3, 0, (14, 15, 12, 1, 0, 0, 1)가 없음

 [0, 1, 0, 0]
0 (1.452539987175031, [0, 1, 2, 2, 2, 3, 3, 3, 3, 1, 3, 9], 73, 733)  
1, 0, (12, 31, 12, 1, 1, 0, 0)가 없음
2 (3.533597285133416, [1, 2, 2, 2, 0, 3, 3, 3, 3, 3, 9], 164, 726)    
3, 0, (14, 23, 12, 1, 1, 0, 1)가 없음

<br>

## 프레임당 가치 기준
 [0, 0, 0, 0]
0 (0.019897808043493576, [0, 1, 2, 2, 2, 3, 3, 3, 3, 1, 3, 9], 1, 733, 375)
1 (1.002472793958591, [1, 2, 2, 2, 3, 3, 3, 3, 1, 3, 9], 46, 725, 300)
2, 0, (12, 15, 12, 1, 2, 1, 0)가 없음
3, 0, (14, 15, 12, 1, 0, 0, 1)가 없음

 [0, 1, 0, 0]
0 (1.452539987175031, [0, 1, 2, 2, 2, 3, 3, 3, 3, 1, 3, 9], 73, 733, 375)
1, 0, (12, 31, 12, 1, 1, 0, 0)가 없음
2 (3.533597285133416, [1, 2, 2, 2, 0, 3, 3, 3, 3, 3, 9], 164, 726, 405)
3, 0, (14, 23, 12, 1, 1, 0, 1)가 없음

 [0, 1, 1, 0]
0 (3.7805835282637794, [0, 1, 2, 2, 2, 3, 3, 3, 3, 1, 3, 9], 190, 733, 375)
1, 0, (12, 31, 12, 1, 2, 1, 0)가 없음
2 (4.358577365037352, [1, 2, 2, 2, 3, 3, 3, 3, 1, 3, 9], 200, 725, 300)
3 (2.7826172623345653, [1, 2, 3, 2, 3, 2, 1, 3, 3, 3, 9], 432, 833, 525)

 [0, 1, 2, 0]
0 (4.505113004294087, [1, 2, 2, 0, 2, 3, 3, 3, 1, 3, 3, 9], 229, 734, 340)
1, 0, (12, 31, 12, 1, 2, 2, 0)가 없음
2 (6.080215424227106, [1, 2, 2, 2, 3, 3, 3, 3, 1, 3, 9], 279, 725, 300)
3 (2.8074473364321513, [1, 2, 2, 3, 3, 3, 1, 3, 2, 3, 9], 431, 832, 525)

 [0, 1, 3, 0]
0 (6.506990122623729, [1, 2, 2, 2, 0, 3, 3, 3, 3, 3, 9], 302, 726, 405)
1, 0, (12, 31, 12, 1, 2, 3, 0)가 없음
2, 0, (12, 23, 12, 1, 2, 4, 0)가 없음
3 (9.479905768956241, [1, 2, 2, 2, 3, 3, 3, 3, 1, 3, 9], 435, 725, 300)

 [0, 1, 3, 1]
0 (9.523475609932744, [1, 2, 2, 2, 0, 3, 3, 3, 3, 3, 9], 442, 726, 405)
1, 0, (14, 31, 12, 1, 2, 3, 1)가 없음
2, 0, (14, 23, 12, 1, 2, 4, 1)가 없음
3 (9.501698655781427, [1, 2, 2, 2, 3, 3, 3, 3, 1, 3, 9], 436, 725, 300)

 [1, 1, 3, 1]
0 (9.000122399505265, [0, 1, 2, 2, 2, 0, 3, 1, 3, 3, 3, 3, 9], 468, 736, 390)
1, 0, (15, 31, 13, 1, 2, 3, 1)가 없음
2, 0, (15, 23, 13, 1, 2, 4, 1)가 없음
3 (9.545021934842094, [1, 2, 2, 2, 0, 3, 3, 3, 3, 3, 9], 443, 726, 405)

 [1, 1, 3, 2]
0 (8.407457021961754, [0, 1, 2, 2, 2, 0, 3, 3, 1, 3, 3, 3, 9], 468, 742, 400)
1 (8.538577661069096, [1, 2, 2, 0, 2, 3, 3, 1, 3, 3, 3, 9], 444, 736, 350)
2, 0, (17, 23, 13, 1, 2, 4, 2)가 없음
3 (9.674299884298193, [1, 2, 2, 2, 0, 3, 3, 3, 3, 3, 9], 449, 726, 405)

 [1, 1, 3, 3]
0 (7.543088803897623, [0, 1, 2, 2, 0, 2, 3, 3, 3, 1, 3, 3, 9], 465, 751, 415)
1 (9.580742502581748, [1, 2, 2, 0, 2, 3, 3, 3, 1, 3, 3, 9], 487, 734, 340)
2, 0, (19, 23, 13, 1, 2, 4, 3)가 없음
3 (10.600791855400248, [1, 2, 2, 2, 0, 3, 3, 3, 3, 3, 9], 492, 726, 405)

 [1, 1, 3, 4]
0 (5.673323254972376, [0, 0, 1, 2, 2, 2, 3, 3, 3, 3, 1, 3, 9], 480, 779, 500)
1 (10.623410577811383, [1, 2, 2, 2, 0, 3, 3, 3, 3, 1, 3, 9], 540, 734, 335)
2, 0, (21, 23, 13, 1, 2, 4, 4)가 없음
3 (11.635015451049053, [1, 2, 2, 2, 0, 3, 3, 3, 3, 3, 9], 540, 726, 405)

 [1, 1, 3, 5]
목표 달성

1. 5__state_date에서 파일런이 가급적 필요한 경우에만 생성되어 몇가지 경우가 빠져있음