# Waffice API 명세서

> 최신개정일: 2025.11.27  
> 최신작성자: 강명석  

## User

/api/user/status  
google id 로 현재 사용자의 상태 (가입완료/승인대기/미인식) 반환  
/api/user/create  
사용자를 승인 대기열에 등록  
/api/user/me  
로그인 성공한 유저 대상으로, 유저 정보 반환  
/user/update  
유저 정보 업데이트  
/api/exct/user/all  
모든 유저 조회  
/api/exct/user/decide  
승인 대기열에 있는 유저 대상으로 승인 또는 거절 판단  
/api/exct/user/info  
google_id 또는 user_id로 특정 유저의 정보 조회  
/api/exct/user/update*  
user 의 정보를 변경  

## Authentication

/auth/google/login  
Google OAuth2.0 시작지점. Google login 화면으로 redirect  

/auth/google/callback  
Google OAuth2.0 callback URL. 이후 처리결과를 FE로 전달  

## Project

/api/project/me  
내가 속해 있는 프로젝트를 조회  
/api/project/info  
project_id 로 프로젝트 정보를 조회. 링크, 팀원까지 정부 공개  
/api/project/update  
프로젝트를 업데이트. 단, 유저가 leader 여야 함. 링크 또한 배열 형태로 주어짐  
/api/project/invite  
프로젝트에 유저를 초대. 단, leader로 초대를 하고 싶다면 자신이 leader 여야 함  
/api/project/kick  
프로젝트에 유저를 제외. 단, 유저가 leader 여야 함  
/api/project/leave  
프로젝트에서 탈퇴  

/api/exct/project/create   
프로젝트를 생성. 인원진이여야 함. 자기 자신이 project 의 leader가 됨  
/api/exct/project/delete  
프로젝트를 삭제  
/api/exct/project/update  
프로젝트를 업데이트. 이때, 링크도 (배열 형태로) 주어짐  