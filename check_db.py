from app import app, db, User

def check_users():
    """Fetches and prints all users, including the face data status."""
    with app.app_context():
        users = User.query.all()
        
        if not users:
            print("--- No Users Found ---")
            print("Please run 'python app.py' first and register a new user.")
            return

        print(f"--- Found {len(users)} User(s) in the Database ---")
        print("{:<4} {:<15} {:<25} {:<20} {:<10}".format("ID", "USERNAME", "EMAIL", "PHONE", "FACE DATA"))
        print("-" * 74)
        
        for u in users:
            # Check if face_data exists (it will be a long Base64 string if saved)
            face_status = "SAVED" if u.face_data and len(u.face_data) > 100 else "MISSING"
            
            print("{:<4} {:<15} {:<25} {:<20} {:<10}".format(
                u.id, 
                u.username, 
                u.email, 
                u.phone, 
                face_status
            ))
        print("-" * 74)

if __name__ == "__main__":
    check_users()