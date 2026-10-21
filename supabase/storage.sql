insert into storage.buckets (id, name, public, file_size_limit)
values ('attachments', 'attachments', false, 26214400)
on conflict (id) do update
set public = excluded.public, file_size_limit = excluded.file_size_limit;

drop policy if exists "attachments: upload into own folder" on storage.objects;
drop policy if exists "attachments: read own folder" on storage.objects;
drop policy if exists "attachments: delete own folder" on storage.objects;

create policy "attachments: upload into own folder"
on storage.objects for insert to authenticated
with check (
  bucket_id = 'attachments'
  and (storage.foldername(name))[1] = (select auth.uid()::text)
);

create policy "attachments: read own folder"
on storage.objects for select to authenticated
using (
  bucket_id = 'attachments'
  and (storage.foldername(name))[1] = (select auth.uid()::text)
);

create policy "attachments: delete own folder"
on storage.objects for delete to authenticated
using (
  bucket_id = 'attachments'
  and (storage.foldername(name))[1] = (select auth.uid()::text)
);
