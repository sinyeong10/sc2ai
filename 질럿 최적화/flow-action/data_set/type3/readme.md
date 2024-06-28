### 아래 조건에 따라 처리
    if 1 not in log[0] and (user_ans == 2 or user_ans == 3):
        user_ans = -1
        print("필요건물 부족")
        end_flag = True
    elif log[0].count(0) >= 4+8:
        user_ans = -1
        print("일꾼 수 과충족")
        end_flag = True
    elif 12+log[0].count(0)+log[0].count(3)*2 >= 15+log[0].count(1)*8 and user_ans != 1:
        print(12+log[0].count(0)+log[0].count(3)*2 , 15+log[0].count(1)*8)
        user_ans = -1
        print("인구수 부족")
        end_flag = True
    elif log[0].count(3) == 2:
        user_ans = 9
        print("완료, 마지막 명령")
        end_flag = True

### 노트북 2대간에 상호작용한 결과 데이터
