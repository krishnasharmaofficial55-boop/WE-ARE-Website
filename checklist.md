# WE ARE. Production checklist

## Before launch
- [ ] Run `supabase/schema.sql`
- [ ] Create `supabase/config.js` from `config.example.js`
- [ ] Add the Supabase URL and anon/publishable key
- [ ] Enable email authentication in Supabase
- [ ] Test signup/login
- [ ] Test two different accounts
- [ ] Test that Account A cannot read Account B's conversation
- [ ] Test real-time messages in two browser windows
- [ ] Add logout
- [ ] Add report/block features before opening messaging publicly
- [ ] Add Privacy Policy and Terms
- [ ] Check mobile layout

## GitHub Pages
1. Put the project files in the repository.
2. Commit and push.
3. Open repository Settings → Pages.
4. Select your production branch and root folder.
5. Save and wait for deployment.
6. Open the generated Pages URL.

## Important
GitHub Pages hosts only the frontend. Supabase provides the database, authentication, and real-time backend.

Do not place private API/service-role keys in HTML or JavaScript.
