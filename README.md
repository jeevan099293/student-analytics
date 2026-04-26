# Student Discipline Leaderboard System

Full-stack web application to track and rank students across schools/colleges using **Discipline Score**.

## Tech Stack

- Frontend: React.js + Tailwind CSS + Axios + Recharts
- Backend: Python Flask + JWT + Role-Based Access Control
- Database: Supabase Postgres

## Discipline Score Formula

$$
\text{Discipline Score} = (\text{Attendance} \times 0.4) + (\text{Behavior} \times 0.3) + (\text{Participation} \times 0.3)
$$

## Roles

1. Student
- View leaderboard
- View own profile (public-safe profile endpoint available)

2. Admin (college_admin)
- Add/edit/delete students in assigned college
- Update attendance, behavior, participation
- Bulk upload CSV
- Reset scores
- View analytics, badges, weekly report

3. Super Admin
- Manage all colleges and admins
- View all students and global data

## Folder Structure

```text
eduvylix perfomance/
  backend/
    app/
      routes/
        auth_routes.py
        admins_routes.py
        colleges_routes.py
        students_routes.py
        leaderboard_routes.py
        analytics_routes.py
      __init__.py
      auth.py
      config.py
      db.py
      utils.py
    .env.example
    requirements.txt
    run.py
  frontend/
    src/
      components/
        Layout.jsx
        PrivateRoute.jsx
        StatCard.jsx
        StudentForm.jsx
        StudentTable.jsx
      hooks/
        useAuth.jsx
      pages/
        HomePage.jsx
        LeaderboardPage.jsx
        StudentProfilePage.jsx
        AdminDashboard.jsx
        LoginPage.jsx
      services/
        api.js
      App.jsx
      main.jsx
      index.css
    index.html
    package.json
    tailwind.config.js
    postcss.config.js
    vite.config.js
```

## Backend Setup

1. Create virtual environment and install dependencies:

```bash
cd backend
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
```

2. Create env file:

```bash
copy .env.example .env
```

Edit `.env` and set `DATABASE_URL` from your Supabase project settings.

3. Run backend:

```bash
python run.py
```

Backend default URL: `http://localhost:5000`

## Frontend Setup

```bash
cd frontend
npm install
npm run dev
```

Frontend default URL: `http://localhost:5173`

If needed, set API base URL:

```bash
set VITE_API_URL=http://localhost:5000/api
```

## Postgres Schema (Supabase)

Schema is defined in [backend/app/models.py](backend/app/models.py).

Legacy MongoDB schema (for reference only):

### 1) Students Collection

```json
{
  "_id": "ObjectId",
  "name": "Aarav Sharma",
  "roll_number": "CSE-2026-001",
  "college_id": "ObjectId(college)",
  "department": "Computer Science",
  "year": 3,
  "attendance": 92,
  "behavior": 88,
  "participation": 85,
  "discipline_score": 88.9,
  "rank_global": 12,
  "rank_college": 3,
  "rank_department": 1,
  "achievements": ["NSS Volunteer", "Debate Finalist"],
  "history": [
    {
      "timestamp": "2026-04-23T09:00:00Z",
      "updated_by": "ObjectId(admin)",
      "reason": "score_update",
      "previous": {
        "attendance": 89,
        "behavior": 86,
        "participation": 82,
        "discipline_score": 85.9
      },
      "new": {
        "attendance": 92,
        "behavior": 88,
        "participation": 85,
        "discipline_score": 88.9
      }
    }
  ],
  "created_at": "ISODate",
  "updated_at": "ISODate"
}
```

### 2) Colleges Collection

```json
{
  "_id": "ObjectId",
  "name": "Vylix Engineering College",
  "location": "Chennai, Tamil Nadu",
  "admin_ids": ["ObjectId(admin1)", "ObjectId(admin2)"],
  "created_at": "ISODate"
}
```

### 3) Admins Collection

```json
{
  "_id": "ObjectId",
  "name": "Priya Menon",
  "email": "priya@vylix.edu",
  "password_hash": "<hashed_password>",
  "role": "college_admin",
  "college_id": "ObjectId(college)",
  "created_at": "ISODate"
}
```

### Relationships

- `students.college_id -> colleges._id`
- `colleges.admin_ids[] -> admins._id`
- `admins.college_id -> colleges._id` for `college_admin`
- `students.history.updated_by -> admins._id`

### Indexing Strategy

- `students: { college_id: 1, roll_number: 1 }` unique
- `students: { discipline_score: -1 }`
- `students: { college_id: 1, department: 1 }`
- `students: { name: 1 }`
- `admins: { email: 1 }` unique
- `colleges: { name: 1 }` unique

## API Endpoints

### Auth

- `POST /api/auth/login`
- `GET /api/auth/me`

### Admins (super_admin)

- `GET /api/admins`
- `POST /api/admins`
- `DELETE /api/admins/:admin_id`

### Colleges

- `GET /api/colleges`
- `POST /api/colleges` (super_admin)
- `PUT /api/colleges/:college_id` (super_admin)
- `DELETE /api/colleges/:college_id` (super_admin)

### Students

- `GET /api/students` (admin/super_admin)
- `POST /api/students` (admin/super_admin)
- `GET /api/students/:student_id` (public safe view + detailed for authenticated admins)
- `PUT /api/students/:student_id` (admin/super_admin)
- `DELETE /api/students/:student_id` (admin/super_admin)
- `POST /api/students/bulk-upload` (CSV, admin/super_admin)
- `POST /api/students/reset-scores` (admin/super_admin)
- `POST /api/students/:student_id/approve` (admin/super_admin)

### Leaderboard

- `GET /api/leaderboard/global`
- `GET /api/leaderboard/college/:college_id`
- `GET /api/leaderboard/department?college_id=...&department=...`

### Analytics

- `GET /api/analytics/trends/:student_id`
- `GET /api/analytics/weekly-report`
- `GET /api/analytics/badges`
- `GET /api/analytics/ai-suggestions/:student_id`

### Notifications

- `GET /api/notifications` (admin/super_admin)
- `PATCH /api/notifications/:notification_id/read` (admin/super_admin)

## Sample API Requests and Responses

### Login

Request:

```http
POST /api/auth/login
Content-Type: application/json

{
  "email": "superadmin@example.com",
  "password": "SuperAdmin@123"
}
```

Response:

```json
{
  "access_token": "<jwt>",
  "admin": {
    "id": "6630...",
    "name": "Platform Super Admin",
    "email": "superadmin@example.com",
    "role": "super_admin",
    "college_id": null
  }
}
```

### Create Student

Request:

```http
POST /api/students
Authorization: Bearer <jwt>
Content-Type: application/json

{
  "name": "Aarav Sharma",
  "roll_number": "CSE-2026-001",
  "college_id": "6630...",
  "department": "Computer Science",
  "year": 3,
  "attendance": 92,
  "behavior": 88,
  "participation": 85
}
```

Response:

```json
{
  "item": {
    "_id": "6631...",
    "name": "Aarav Sharma",
    "discipline_score": 88.9,
    "rank_global": null
  }
}
```

### Global Leaderboard

Request:

```http
GET /api/leaderboard/global?search=aarav&college_id=6630...
```

Response:

```json
{
  "items": [
    {
      "_id": "6631...",
      "name": "Aarav Sharma",
      "college_id": "6630...",
      "department": "Computer Science",
      "discipline_score": 88.9,
      "rank_global": 12
    }
  ]
}
```

## Frontend Component Structure

- `Layout`: top navigation and route outlet
- `PrivateRoute`: JWT-based guard for admin pages
- `StudentTable`: leaderboard and admin table display
- `StudentForm`: add/edit form with live discipline score preview
- `StatCard`: dashboard cards

## Frontend Pages

- Home Page
- Leaderboard Page
- Student Profile Page
- Admin Dashboard
- School Dashboard

## Security and Controls

- JWT authentication for admin/super admin
- RBAC by role (`college_admin`, `super_admin`)
- College-level data boundaries enforced for college admins
- Audit trail on all score-changing operations

## Advanced Features Included

- Graphs: trend and weekly report charts
- Weekly reports: score update activity by college
- Badges: Best Discipline and Most Active
- Notifications alternative: API-ready score history events in `history`
- AI-based suggestions: heuristic recommendations from metrics

## Notes

- The backend auto-creates a bootstrap super admin from `.env` on first login call.
- Rank recalculation happens after create/update/delete/reset/bulk-upload operations.