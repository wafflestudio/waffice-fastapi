# 회원 관련 DB 및 API 명세서

> 최초작성일 2025-09-26  
> 최신개정일 2025-09-26
> 작성자 [23기 강명석](mailto:tomskang@naver.com)
> 최신개정자 [23기 강명석](mailto:tomskang@naver.com)

# DB 구조

## 회원 DB `user`
```sql
CREATE TABLE `user` (
  `userid`        BIGINT AUTO_INCREMENT PRIMARY KEY,
  `google_id`     VARCHAR(255) NOT NULL UNIQUE,
  `type`          ENUM('programmer','designer') NOT NULL,
  `privilege`     ENUM('준회원','정회원','활동회원') NOT NULL,
  `admin`         TINYINT NOT NULL DEFAULT 0, -- 0/1/2
  `atime`         BIGINT NOT NULL, -- access time (unix-like)
  `ctime`         BIGINT NOT NULL, -- create time
  `mtime`         BIGINT NOT NULL, -- modify time
  `time_quit`     BIGINT NULL, -- 탈퇴시간
  `time_stop`     BIGINT NULL, -- 정지시간
  `info_phonecall` VARCHAR(32),
  `info_email`     VARCHAR(255),
  `info_major`     VARCHAR(128),
  `info_cardinal`  VARCHAR(32),
  `info_position`  VARCHAR(128),
  `info_work`      VARCHAR(128),
  `info_introduce` TEXT,
  `info_sns1`      VARCHAR(255),
  `info_sns2`      VARCHAR(255),
  `info_sns3`      VARCHAR(255),
  `info_sns4`      VARCHAR(255),
  `id_github`      VARCHAR(255),
  `id_slack`       VARCHAR(255),
  `receive_email`  BOOLEAN DEFAULT TRUE,
  `receive_sms`    BOOLEAN DEFAULT TRUE
);
```

## 회원 변동사항 DB `user_history`
```sql
CREATE TABLE `user_history` (
  `id`              BIGINT AUTO_INCREMENT PRIMARY KEY,
  `userid`          BIGINT NOT NULL,
  `type`            ENUM('생성','탈퇴','징계','프로젝트가입','프로젝트탈퇴') NOT NULL,
  `description`     TEXT,
  `curr_privilege`  ENUM('준회원','정회원','활동회원') NULL,
  `curr_time_stop`  BIGINT NULL,
  `prec_privilege`  ENUM('준회원','정회원','활동회원') NULL,
  `prec_time_stop`  BIGINT NULL,
  FOREIGN KEY (`userid`) REFERENCES `user`(`userid`) ON DELETE CASCADE
);
```

## SQL Trigger


# API 구조

# API 구조

## /api/user/create

- **Method**: `POST`
- **URL**: `/api/user/create`
- **설명**: OAuth2.0 로그인 후 가입 대기열(`user_pending`)에 등록
- **Request Body**
```json
{
  "google_id": "google-oauth-sub",
  "email": "user@snu.ac.kr",
  "name": "홍길동",
  "profile_picture": "https://lh3.googleusercontent.com/..."
}
```
- **Response**
```json
{
  "ok": true,
  "id": 123,
  "ctime": "생성시간"
}
```
- **Status Codes**
  - `201 Created`
  - `400 Bad Request`
  - `409 Conflict`


## /api/user/enroll

- **Method**: `POST`
- **URL**: `/api/user/enroll`
- **설명**: 가입 대기열(`user_pending`)의 특정 유저를 정식 회원(`user`)으로 등록
- **Request Body**
```json
{
  "pending_id": 123,
  "type": "programmer",
  "privilege": "준회원"
}
```
- **Response**
```json
{
  "ok": true,
  "userid": 45
}
```
- **Status Codes**
  - `201 Created`
  - `404 Not Found`
  - `409 Conflict`


## /api/user/deny

- **Method**: `POST`
- **URL**: `/api/user/deny`
- **설명**: 가입 대기열의 특정 유저 요청을 거절
- **Request Body**
```json
{
  "pending_id": 123,
  "reason": "허용되지 않은 이메일 도메인"
}
```
- **Response**
```json
{
  "ok": true,
  "status": "거절"
}
```
- **Status Codes**
  - `200 OK`
  - `404 Not Found`


## /api/user/info

- **Method**: `GET`
- **URL**: `/api/user/info?userid=45`
- **설명**: 특정 유저의 상세 정보 + user_history 포함 조회
- **Response**
```json
{
  "ok": true,
  "user": {
    "userid": 45,
    "google_id": "xxxx",
    "type": "programmer",
    "privilege": "정회원",
    "info_email": "user@snu.ac.kr"
  },
  "history": [
    { "id": 1, "type": "생성", "ctime": 1691234567 },
    { "id": 2, "type": "프로젝트가입", "ctime": 1694567890 }
  ]
}
```
- **Status Codes**
  - `200 OK`
  - `404 Not Found`


## /api/user/all

- **Method**: `GET`
- **URL**: `/api/user/all`
- **설명**: 전체 회원 목록 조회
- **Response**
```json
{
  "ok": true,
  "users": [
    { "userid": 45, "name": "홍길동", "privilege": "정회원" },
    { "userid": 46, "name": "김철수", "privilege": "준회원" }
  ]
}
```
- **Status Codes**
  - `200 OK`


## /api/user/update

- **Method**: `POST`
- **URL**: `/api/user/update`
- **설명**: 운영진 권한으로 유저 정보 강제 업데이트
- **Request Body**
```json
{
  "userid": 45,
  "privilege": "활동회원",
  "admin": 1
}
```
- **Response**
```json
{
  "ok": true,
  "userid": 45
}
```
- **Status Codes**
  - `200 OK`
  - `404 Not Found`
  - `403 Forbidden`


## /api/user/access

- **Method**: `POST`
- **URL**: `/api/user/access`
- **설명**: 홈페이지 접근 기록 (유저 atime 업데이트)
- **Request Body**
```json
{
  "userid": 45
}
```
- **Response**
```json
{
  "ok": true,
  "atime": 1697891234
}
```
- **Status Codes**
  - `200 OK`
  - `404 Not Found`


## /api/userhist/create

- **Method**: `POST`
- **URL**: `/api/userhist/create`
- **설명**: 새로운 userHistory 기록 생성 및 적용
- **Request Body**
```json
{
  "userid": 45,
  "type": "징계",
  "description": "3개월 정지",
  "curr_privilege": "정회원",
  "curr_time_stop": 1700000000,
  "prec_privilege": "활동회원"
}
```
- **Response**
```json
{
  "ok": true,
  "id": 77
}
```
- **Status Codes**
  - `201 Created`
  - `404 Not Found`


## /api/userhist/info

- **Method**: `GET`
- **URL**: `/api/userhist/info?id=77`
- **설명**: 특정 userHistory 상세 정보 조회
- **Response**
```json
{
  "ok": true,
  "history": {
    "id": 77,
    "userid": 45,
    "type": "징계",
    "description": "3개월 정지",
    "curr_privilege": "정회원",
    "curr_time_stop": 1700000000,
    "prec_privilege": "활동회원"
  }
}
```
- **Status Codes**
  - `200 OK`
  - `404 Not Found`


## /api/userhist/all

- **Method**: `GET`
- **URL**: `/api/userhist/all`
- **설명**: 전체 userHistory 조회
- **Response**
```json
{
  "ok": true,
  "histories": [
    { "id": 1, "userid": 45, "type": "생성" },
    { "id": 2, "userid": 46, "type": "탈퇴" }
  ]
}
```
- **Status Codes**
  - `200 OK`

