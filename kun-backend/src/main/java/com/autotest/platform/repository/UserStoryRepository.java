package com.autotest.platform.repository;

import com.autotest.platform.entity.UserStory;
import org.springframework.data.domain.Page;
import org.springframework.data.domain.Pageable;
import org.springframework.data.jpa.repository.JpaRepository;
import org.springframework.data.jpa.repository.Query;
import org.springframework.data.repository.query.Param;
import org.springframework.stereotype.Repository;

import java.util.List;
import java.util.Optional;

@Repository
public interface UserStoryRepository extends JpaRepository<UserStory, Long> {

    Optional<UserStory> findByUsNumber(String usNumber);

    Optional<UserStory> findByUsNumberAndTenantId(String usNumber, Long tenantId);

    Optional<UserStory> findByIdAndTenantId(Long id, Long tenantId);

    boolean existsByUsNumber(String usNumber);

    boolean existsByUsNumberAndTenantId(String usNumber, Long tenantId);

    Page<UserStory> findByTenantId(Long tenantId, Pageable pageable);

    @Query("SELECT us FROM UserStory us WHERE us.tenantId = :tenantId AND us.status = :status")
    Page<UserStory> findByStatusAndTenantId(@Param("tenantId") Long tenantId,
                                            @Param("status") UserStory.Status status,
                                            Pageable pageable);

    @Query("SELECT us FROM UserStory us WHERE us.tenantId = :tenantId AND us.priority = :priority")
    Page<UserStory> findByPriorityAndTenantId(@Param("tenantId") Long tenantId,
                                              @Param("priority") UserStory.Priority priority,
                                              Pageable pageable);

    @Query("SELECT us FROM UserStory us WHERE us.tenantId = :tenantId AND us.createdBy.id = :userId")
    Page<UserStory> findByCreatedByAndTenantId(@Param("tenantId") Long tenantId,
                                               @Param("userId") Long userId,
                                               Pageable pageable);

    @Query("SELECT us FROM UserStory us WHERE us.tenantId = :tenantId AND us.sprint = :sprint")
    List<UserStory> findBySprintAndTenantId(@Param("tenantId") Long tenantId,
                                            @Param("sprint") String sprint);

    @Query("SELECT us FROM UserStory us WHERE us.tenantId = :tenantId AND us.epic = :epic")
    List<UserStory> findByEpicAndTenantId(@Param("tenantId") Long tenantId,
                                          @Param("epic") String epic);

    @Query("SELECT us FROM UserStory us WHERE us.tenantId = :tenantId AND (" +
            "us.usNumber LIKE %:keyword% OR " +
            "us.title LIKE %:keyword% OR " +
            "us.description LIKE %:keyword%)")
    Page<UserStory> searchUserStories(@Param("tenantId") Long tenantId,
                                      @Param("keyword") String keyword,
                                      Pageable pageable);

    @Query("SELECT us FROM UserStory us WHERE us.tenantId = :tenantId AND " +
            "(:keyword IS NULL OR :keyword = '' OR " +
            "LOWER(us.usNumber) LIKE LOWER(CONCAT('%', :keyword, '%')) OR " +
            "LOWER(us.title) LIKE LOWER(CONCAT('%', :keyword, '%')) OR " +
            "LOWER(COALESCE(us.description, '')) LIKE LOWER(CONCAT('%', :keyword, '%'))) " +
            "AND (:status IS NULL OR us.status = :status) " +
            "AND (:priority IS NULL OR us.priority = :priority) " +
            "AND (:sprint IS NULL OR :sprint = '' OR us.sprint = :sprint)")
    Page<UserStory> findByFilters(@Param("tenantId") Long tenantId,
                                  @Param("keyword") String keyword,
                                  @Param("status") UserStory.Status status,
                                  @Param("priority") UserStory.Priority priority,
                                  @Param("sprint") String sprint,
                                  Pageable pageable);

    @Query("SELECT DISTINCT us.sprint FROM UserStory us WHERE us.tenantId = :tenantId AND us.sprint IS NOT NULL AND us.sprint <> '' ORDER BY us.sprint")
    List<String> findAllSprints(@Param("tenantId") Long tenantId);

    @Query("SELECT COUNT(us) FROM UserStory us WHERE us.tenantId = :tenantId AND us.status = :status")
    long countByStatus(@Param("tenantId") Long tenantId,
                       @Param("status") UserStory.Status status);

    @Query("SELECT COUNT(us) FROM UserStory us WHERE us.tenantId = :tenantId AND us.priority = :priority")
    long countByPriority(@Param("tenantId") Long tenantId,
                         @Param("priority") UserStory.Priority priority);

    long countByTenantId(Long tenantId);
}
